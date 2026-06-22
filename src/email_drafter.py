"""Email draft generation (FR-6).

Generates a plain-English message for each exception that actually requires
communication -- Approved exceptions need no message. Uses Claude for a
natural, context-aware draft when available; otherwise renders the Jinja2
fallback template so the feature still works with zero credentials.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src import llm_client
from src.models import Action, POInvoiceRecord, Severity, TriageResult
from src.rag import retriever as rag_retriever

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

DEADLINE_DAYS = {Severity.HIGH: 3, Severity.MEDIUM: 5, Severity.LOW: 7}

_REQUIRED_ACTION_TEXT = {
    Action.CLARIFY: "Please confirm the correct figure/data point and resubmit documentation so we can finalize this exception.",
    Action.REJECT: "This invoice has been rejected as a likely duplicate submission; no payment will be issued unless you can show this is a distinct order.",
    Action.ESCALATE: "This exception has been escalated to a procurement manager for review and approval before disposition.",
}


def _describe_issue(result: TriageResult, record: POInvoiceRecord) -> str:
    t = result.exception_type
    if t == "Price Variance":
        return (
            f"The invoiced amount (${record.invoice_amount:,.2f}) differs from the PO amount "
            f"(${record.po_amount:,.2f}) by ${result.financial_variance:,.2f}."
        )
    if t == "Quantity Mismatch":
        return f"Quantity received ({record.qty_received}) does not match quantity ordered ({record.qty_ordered})."
    if t == "Duplicate PO":
        return f"This PO matches another PO from the same vendor for the same amount within a few days, suggesting a duplicate submission."
    if t == "Missing Fields":
        blanks = [name for name, val in (("Vendor ID", record.vendor_id), ("GL Code", record.gl_code)) if not val]
        if record.delivery_date is None:
            blanks.append("Delivery Date")
        return f"The following required field(s) are blank on this record: {', '.join(blanks) or 'one or more required fields'}."
    if t == "Terms Conflict":
        return (
            f"The invoice states payment terms of '{record.payment_terms_invoice}', which differs from the "
            f"contracted terms of '{record.payment_terms_contract}'."
        )
    return "A discrepancy was identified between the PO and invoice data."


def draft_email(result: TriageResult, record: POInvoiceRecord, reference_date: date | None = None) -> str | None:
    if result.recommended_action == Action.APPROVE:
        return None

    reference_date = reference_date or date.today()
    deadline = (reference_date + timedelta(days=DEADLINE_DAYS[result.severity])).isoformat()
    issue_detail = _describe_issue(result, record)
    required_action = _REQUIRED_ACTION_TEXT[result.recommended_action]
    vendor_name = record.vendor_name or "Vendor"

    # Escalations are an internal note to the procurement manager, not a
    # vendor-facing message -- everything else (Clarify / Reject) goes to
    # the vendor's AP team.
    is_internal = result.recommended_action == Action.ESCALATE
    audience = f"Procurement Manager (re: vendor {vendor_name})" if is_internal else f"{vendor_name} Accounts Team"

    # Re-fetch full text for the citations the classifier already validated (TriageResult
    # only stores the source_file names, not full chunk text, to keep the report lean). The
    # eligible chunk set is determined by vendor_id, not the query text, so filtering down
    # to result.citations here guarantees we only ever cite what was already verified --
    # never a fresh, unvalidated retrieval result.
    retrieved_context = []
    if result.citations:
        query = rag_retriever.build_query(result.exception_type, record)
        candidates = rag_retriever.retrieve(record.vendor_id, query, k=len(result.citations) + 2)
        retrieved_context = [c for c in candidates if c.source_file in result.citations]

    if llm_client.is_available():
        try:
            return llm_client.draft_email(
                po_number=result.po_number, vendor_name=audience, exception_type=result.exception_type,
                issue_detail=issue_detail, required_action=required_action, deadline=deadline,
                retrieved_context=retrieved_context,
            )
        except llm_client.LLMUnavailable:
            pass  # fall back to template below

    template = _env.get_template("email.txt")
    return template.render(
        po_number=result.po_number, exception_type=result.exception_type,
        issue_detail=issue_detail, required_action=required_action, deadline=deadline,
        subject_prefix="[Internal Escalation] " if is_internal else "",
        salutation=f"Dear Procurement Manager," if is_internal else f"Dear {vendor_name} Accounts Team,",
        closing_note="Please review and approve a disposition before the deadline." if is_internal
            else "If you believe this discrepancy is in error, please reply with supporting documentation.",
    )
