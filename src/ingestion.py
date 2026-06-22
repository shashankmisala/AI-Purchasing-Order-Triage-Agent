"""Data ingestion + validation (FR-1).

Reads PO and invoice exports (CSV or .xlsx), merges them on PO Number into a
single candidate DataFrame, and validates each row against
`models.POInvoiceRecord`. Malformed rows (bad types, unparseable dates,
unmatched join keys) are dropped and written to an error log rather than
raising -- a single bad row should never sink a 10k-row batch.

Note the distinction from "missing fields" as a *business* exception: a
blank Vendor ID / GL Code / Delivery Date is a valid, classifiable PO
exception (see config/exception_types.yaml), not a schema failure, so it
passes validation here and is left for the rules/classifier layer.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

import pandas as pd
from pydantic import ValidationError

from src.models import POInvoiceRecord, ValidationErrorRecord

PathLike = Union[str, Path]

# Required columns per FR-1 (human-readable headers as they'd appear in an ERP export).
PO_REQUIRED = ["PO Number", "Vendor ID", "PO Amount", "Quantity Ordered", "GL Code", "Payment Terms", "PO Date"]
INVOICE_REQUIRED = ["PO Number", "Invoice Amount", "Quantity Received", "Payment Terms"]

PO_COLUMN_MAP = {
    "po number": "po_number",
    "vendor id": "vendor_id",
    "vendor name": "vendor_name",
    "industry": "industry",
    "po amount": "po_amount",
    "quantity ordered": "qty_ordered",
    "gl code": "gl_code",
    "payment terms": "payment_terms_contract",
    "po date": "po_date",
    "vendor payment history": "vendor_payment_history_flag",
}
INVOICE_COLUMN_MAP = {
    "po number": "po_number",
    "invoice amount": "invoice_amount",
    "quantity received": "qty_received",
    "payment terms": "payment_terms_invoice",
    "invoice date": "invoice_date",
    "delivery date": "delivery_date",
}


class IngestionError(Exception):
    """Raised for batch-level schema problems (missing required columns)."""


def _read_table(path: PathLike) -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path)
    return pd.read_csv(path)


def _normalize_columns(df: pd.DataFrame, column_map: dict[str, str], required: list[str], source: str) -> pd.DataFrame:
    lower_lookup = {c.strip().lower(): c for c in df.columns}
    missing = [req for req in required if req.lower() not in lower_lookup]
    if missing:
        raise IngestionError(f"{source} file is missing required column(s): {', '.join(missing)}")

    rename = {}
    for lower_name, original_name in lower_lookup.items():
        if lower_name in column_map:
            rename[original_name] = column_map[lower_name]
    return df.rename(columns=rename)


def _to_native(value):
    """Convert pandas/NumPy scalars (incl. NaT/NaN) to plain Python values or None."""
    if pd.isna(value):
        return None
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().date()
    return value


def ingest(po_path: PathLike, invoice_path: PathLike) -> tuple[list[POInvoiceRecord], pd.DataFrame]:
    """Returns (valid_records, error_log_df). Raises IngestionError on missing columns."""

    po_df = _normalize_columns(_read_table(po_path), PO_COLUMN_MAP, PO_REQUIRED, "PO export")
    invoice_df = _normalize_columns(_read_table(invoice_path), INVOICE_COLUMN_MAP, INVOICE_REQUIRED, "Invoice export")

    po_df["po_date"] = pd.to_datetime(po_df["po_date"], errors="coerce")
    for col in ("invoice_date", "delivery_date"):
        if col in invoice_df.columns:
            invoice_df[col] = pd.to_datetime(invoice_df[col], errors="coerce")

    merged = po_df.merge(invoice_df, on="po_number", how="outer", indicator=True, suffixes=("_po", "_inv"))

    errors: list[ValidationErrorRecord] = []
    valid_records: list[POInvoiceRecord] = []

    for idx, row in merged.reset_index(drop=True).iterrows():
        po_number = row.get("po_number")
        if row["_merge"] == "left_only":
            errors.append(ValidationErrorRecord(row_index=idx, po_number=po_number, error="No matching invoice record for this PO"))
            continue
        if row["_merge"] == "right_only":
            errors.append(ValidationErrorRecord(row_index=idx, po_number=po_number, error="Invoice references a PO Number not present in the PO export"))
            continue

        payload = {k: _to_native(row.get(k)) for k in (
            "po_number", "vendor_id", "vendor_name", "industry", "po_amount", "invoice_amount",
            "qty_ordered", "qty_received", "gl_code", "payment_terms_invoice", "payment_terms_contract",
            "po_date", "invoice_date", "delivery_date", "vendor_payment_history_flag",
        )}
        try:
            valid_records.append(POInvoiceRecord(**payload))
        except ValidationError as exc:
            errors.append(ValidationErrorRecord(row_index=idx, po_number=po_number, error=str(exc.errors()[0]["msg"])))

    error_df = pd.DataFrame([e.model_dump() for e in errors])
    return valid_records, error_df
