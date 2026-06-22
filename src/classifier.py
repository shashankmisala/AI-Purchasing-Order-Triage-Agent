"""Hybrid rule + LLM exception classifier (PRD 3.2, FR-2).

Rules run first and handle the unambiguous majority of rows. Only when a row
matches more than one exception type -- a genuinely ambiguous case -- does
this reach for the LLM, which keeps API cost low per NFR (Cost). If the LLM
is unavailable or fails, FR-2's tie-break ("select highest-severity type")
is applied deterministically instead.

RAG: for ambiguous rows, the vendor's contract / the AP policy manual / past
precedent are retrieved (local, free -- no API cost) before the LLM call, so
the model can ground its classification and rationale in an actual cited
document instead of reasoning from the flat structured row alone.
"""
from __future__ import annotations

from src import llm_client, recommender, rules, scorer
from src.models import Action, ClassificationMethod, POInvoiceRecord, Severity, TriageResult
from src.rag import retriever as rag_retriever

SEVERITY_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

RULE_CONFIDENCE = 0.95
RULE_FALLBACK_CONFIDENCE = 0.80


def _highest_severity_type(candidate_types: list[str], cfg: dict) -> str:
    return max(
        candidate_types,
        key=lambda t: SEVERITY_RANK[cfg["exception_types"][t]["default_severity"]],
    )


def _normalize_llm_type(raw: str, candidate_types: list[str], cfg: dict) -> str | None:
    """Maps an LLM-returned exception_type string back to our internal key,
    accepting either the key itself or the human-readable label.
    """
    if not raw:
        return None
    key_guess = raw.strip().lower().replace(" ", "_")
    if key_guess in candidate_types:
        return key_guess
    for t in candidate_types:
        if cfg["exception_types"][t]["label"].lower() == raw.strip().lower():
            return t
    return None


def classify_record(
    record: POInvoiceRecord, duplicate_po_numbers: set[str], cfg: dict
) -> TriageResult | None:
    """Returns a TriageResult, or None if the record triggers no exception
    (a clean PO needs no triage)."""

    candidates = rules.match_all(record, duplicate_po_numbers, cfg)
    if not candidates:
        return None

    llm_result: dict | None = None
    retrieved_context: list = []
    if len(candidates) == 1:
        exception_type = candidates[0]
        confidence = RULE_CONFIDENCE
        method = ClassificationMethod.RULE
    else:
        # Retrieval is local TF-IDF search -- no API cost -- so it always runs for an
        # ambiguous row, independent of whether the LLM call below succeeds. The query is
        # built from the rule engine's own deterministic best guess (highest-severity
        # candidate), not anything LLM-dependent, since retrieval happens before we know
        # what the LLM will say.
        baseline_type = _highest_severity_type(candidates, cfg)
        query = rag_retriever.build_query(cfg["exception_types"][baseline_type]["label"], record)
        try:
            retrieved_context = rag_retriever.retrieve(record.vendor_id, query)
        except Exception:
            retrieved_context = []

        if llm_client.is_available():
            try:
                llm_result = llm_client.classify_exception(record, candidates, retrieved_context=retrieved_context)
            except llm_client.LLMUnavailable:
                llm_result = None

        normalized = _normalize_llm_type(llm_result.get("exception_type") if llm_result else None, candidates, cfg)
        if llm_result and normalized:
            exception_type = normalized
            confidence = float(llm_result.get("confidence", 0.85))
            method = ClassificationMethod.LLM
        else:
            exception_type = _highest_severity_type(candidates, cfg)
            confidence = RULE_FALLBACK_CONFIDENCE
            method = ClassificationMethod.RULE_FALLBACK

    confidence = max(0.0, min(1.0, confidence))
    score, severity = scorer.score_record(record, exception_type)
    threshold = cfg["human_review_confidence_threshold"]

    if method == ClassificationMethod.LLM and llm_result and llm_result.get("recommended_action"):
        try:
            llm_action = Action(llm_result["recommended_action"])
        except ValueError:
            llm_action = None

        # Independent baseline: what would the deterministic recommender
        # assign for this exception_type/severity on its own, ignoring
        # whatever the LLM said? Fields like vendor_name/gl_code that feed
        # the classifier prompt are untrusted (vendor-supplied) data, so a
        # single LLM call cannot be trusted to both classify that data AND
        # self-certify the confidence that decides whether a human reviews
        # it -- a prompt injection in that same data could forge both at
        # once. Skipping review therefore requires the LLM's suggested
        # action to agree with this independent baseline, not just a
        # self-reported confidence above threshold.
        rule_action, rule_rationale, _ = recommender.recommend_action(
            exception_type, severity, RULE_CONFIDENCE, threshold, record.vendor_payment_history_flag
        )
        corroborated = llm_action is not None and llm_action == rule_action

        if corroborated and confidence >= threshold:
            action = llm_action
            rationale = llm_result.get("rationale", "LLM-assisted classification of an ambiguous exception.")
            needs_review = False
            # Trust a citation only if it's both claimed by the LLM AND actually one of the
            # documents we really retrieved and showed it -- never let a (possibly
            # injection-influenced) model response cite a source it was never given.
            retrieved_source_files = {c.source_file for c in retrieved_context}
            citations = [c for c in (llm_result.get("citations") or []) if c in retrieved_source_files]
        else:
            action, rationale, needs_review = rule_action, rule_rationale, True
            citations = []
    else:
        action, rationale, needs_review = recommender.recommend_action(
            exception_type, severity, confidence, threshold, record.vendor_payment_history_flag
        )
        citations = []

    return TriageResult(
        po_number=record.po_number,
        vendor_id=record.vendor_id,
        vendor_name=record.vendor_name,
        exception_type=cfg["exception_types"][exception_type]["label"],
        severity=severity,
        urgency_score=score,
        citations=citations,
        recommended_action=action,
        rationale=rationale,
        confidence=round(confidence, 2),
        classification_method=method,
        needs_human_review=needs_review,
        financial_variance=rules.financial_variance(record),
    )


def classify_batch(records: list[POInvoiceRecord], cfg: dict | None = None) -> list[TriageResult]:
    cfg = cfg or rules.load_config()
    duplicate_po_numbers = rules.find_duplicates(records, cfg)
    results = []
    for record in records:
        result = classify_record(record, duplicate_po_numbers, cfg)
        if result is not None:
            results.append(result)
    return results
