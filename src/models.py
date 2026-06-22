"""Pydantic schemas for the PO Exception Triage Agent.

These models implement FR-1 (schema validation) and define the shape of the
triage output used throughout the pipeline (FR-2 through FR-5).
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Severity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ClassificationMethod(str, Enum):
    RULE = "rule"
    LLM = "llm"
    RULE_FALLBACK = "rule-fallback"


class Action(str, Enum):
    APPROVE = "Approve"
    ESCALATE = "Escalate to Manager"
    REJECT = "Reject Invoice"
    CLARIFY = "Request Vendor Clarification"


class POInvoiceRecord(BaseModel):
    """A single merged PO + invoice line, post-join, pre-classification.

    Required columns per FR-1: PO Number, Vendor ID, PO Amount, Invoice Amount,
    Quantity Ordered, Quantity Received, GL Code, Payment Terms, PO Date.

    Note: vendor_id / gl_code / delivery_date are allowed to be blank at the
    *schema* level because a blank value is itself a business exception
    (Missing Fields, see config/exception_types.yaml) rather than a malformed
    record. Malformed records (e.g. non-numeric amounts, unparseable dates)
    fail validation and are routed to the error log instead.
    """

    po_number: str = Field(min_length=1)
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    industry: Optional[str] = None

    po_amount: float = Field(gt=0)
    invoice_amount: float = Field(gt=0)

    qty_ordered: int = Field(ge=0)
    qty_received: int = Field(ge=0)

    gl_code: Optional[str] = None

    payment_terms_invoice: Optional[str] = None
    payment_terms_contract: Optional[str] = None

    po_date: date
    invoice_date: Optional[date] = None
    delivery_date: Optional[date] = None

    # Used by the severity scorer (FR-3) as a financial-risk signal.
    vendor_payment_history_flag: Optional[str] = None  # "good" | "late" | "disputed"

    @field_validator("vendor_id", "gl_code", "payment_terms_invoice", "payment_terms_contract", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if v is None:
            return None
        s = str(v).strip()
        return s if s else None


class ValidationErrorRecord(BaseModel):
    row_index: int
    po_number: Optional[str] = None
    error: str


class TriageResult(BaseModel):
    """One row of the output triage report (FR-5)."""

    po_number: str
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None

    exception_type: str
    severity: Severity
    urgency_score: int = Field(ge=1, le=10)

    recommended_action: Action
    rationale: str

    confidence: float = Field(ge=0.0, le=1.0)
    classification_method: ClassificationMethod
    needs_human_review: bool

    financial_variance: float = 0.0
    email_draft: Optional[str] = None

    # RAG citations: source_file values for any vendor contract / AP policy / precedent
    # passage the system actually retrieved and relied on for this exception's rationale.
    # Empty when retrieval found nothing relevant (never fabricated to fill the field).
    citations: list[str] = Field(default_factory=list)


class BatchSummary(BaseModel):
    total_exceptions: int
    by_type: dict[str, int]
    by_severity: dict[str, int]
    estimated_financial_exposure: float
    high_count: int
    validation_errors: int
    processing_seconds: float
