"""Severity scoring (FR-3).

Produces a numeric urgency score 1-10 from financial impact, exception type,
and vendor payment history, then maps that score to a HIGH/MEDIUM/LOW band
via config/exception_types.yaml. The score is always computed deterministically
(not delegated to the LLM) so every triage result is reproducible and
auditable end-to-end (NFR: Auditability) -- an LLM-suggested severity is
informational only and never overrides this.
"""
from __future__ import annotations

from src.models import POInvoiceRecord, Severity
from src.rules import financial_variance, load_config

# Starting point within each type's severity band (PRD 3.1 default severities).
TYPE_BASE_SCORE = {
    "price_variance": 7,
    "quantity_mismatch": 7,
    "duplicate_po": 5,
    "missing_fields": 4,
    "terms_conflict": 2,
}

HISTORY_ADJUSTMENT = {
    "good": 0,
    "late": 1,
    "disputed": 2,
}


def urgency_score(record: POInvoiceRecord, exception_type: str) -> int:
    score = TYPE_BASE_SCORE.get(exception_type, 5)

    variance_pct = financial_variance(record) / record.po_amount if record.po_amount else 0
    score += min(2, round(variance_pct * 10))  # up to +2 for large price/qty-driven $ swings

    score += HISTORY_ADJUSTMENT.get((record.vendor_payment_history_flag or "good").lower(), 0)

    return max(1, min(10, round(score)))


def severity_from_score(score: int) -> Severity:
    bands = load_config()["severity_bands"]
    for name, (lo, hi) in bands.items():
        if lo <= score <= hi:
            return Severity(name)
    return Severity.LOW


def score_record(record: POInvoiceRecord, exception_type: str) -> tuple[int, Severity]:
    score = urgency_score(record, exception_type)
    return score, severity_from_score(score)
