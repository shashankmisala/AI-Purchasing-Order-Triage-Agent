"""Action recommendation (FR-4).

Deterministic default used whenever the row was resolved by the rule engine
(the common case). When the LLM was already invoked to disambiguate a
multi-match row, its recommended_action + rationale are used instead (see
classifier.py) since it has the fuller context -- this function only
provides the rule-based fallback / baseline.
"""
from __future__ import annotations

from src.models import Action, Severity

# Default disposition per exception type + severity. Tuned to the kind of
# judgment call a junior AP analyst would make per PRD section 1.1.
_DEFAULT_ACTION = {
    "price_variance": {Severity.HIGH: Action.ESCALATE, Severity.MEDIUM: Action.CLARIFY, Severity.LOW: Action.CLARIFY},
    "quantity_mismatch": {Severity.HIGH: Action.ESCALATE, Severity.MEDIUM: Action.CLARIFY, Severity.LOW: Action.CLARIFY},
    "duplicate_po": {Severity.HIGH: Action.REJECT, Severity.MEDIUM: Action.REJECT, Severity.LOW: Action.CLARIFY},
    "missing_fields": {Severity.HIGH: Action.CLARIFY, Severity.MEDIUM: Action.CLARIFY, Severity.LOW: Action.CLARIFY},
    "terms_conflict": {Severity.HIGH: Action.ESCALATE, Severity.MEDIUM: Action.CLARIFY, Severity.LOW: Action.CLARIFY},
}

_RATIONALE_TEMPLATE = {
    Action.APPROVE: "Variance is within tolerance and vendor history is clean; no further action needed.",
    Action.ESCALATE: "Financial exposure and severity are high enough to require manager sign-off before disposition.",
    Action.REJECT: "Pattern matches a duplicate submission; reject to prevent an overpayment.",
    Action.CLARIFY: "Discrepancy needs vendor input before this can be approved or rejected.",
}


def recommend_action(
    exception_type: str, severity: Severity, confidence: float, human_review_threshold: float,
    vendor_history: str | None = None,
) -> tuple[Action, str, bool]:
    needs_human_review = confidence < human_review_threshold
    if needs_human_review:
        return Action.CLARIFY, "Classification confidence is below the review threshold; routed to a human for confirmation.", True

    # A LOW-severity terms conflict from a vendor with a clean payment history
    # is a minor deviation, not worth a clarification round-trip -- approve
    # with the contracted terms applied.
    if exception_type == "terms_conflict" and severity == Severity.LOW and (vendor_history or "good").lower() == "good":
        return Action.APPROVE, "Terms deviation is minor and vendor payment history is clean; approved under standard contract terms.", False

    action = _DEFAULT_ACTION.get(exception_type, {}).get(severity, Action.CLARIFY)
    return action, _RATIONALE_TEMPLATE[action], False
