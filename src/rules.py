"""Deterministic rule-based pre-filter (PRD 3.2).

Handles the ~60% of exceptions that are clear-cut without needing an LLM
call: each function below implements one exception type's trigger condition
from PRD section 3.1. Duplicate detection is batch-level (it needs to see
every record for a vendor), so it's computed once up front rather than
per-row.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import yaml

from src.models import POInvoiceRecord

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "exception_types.yaml"


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def financial_variance(record: POInvoiceRecord) -> float:
    return round(abs(record.invoice_amount - record.po_amount), 2)


def match_price_variance(record: POInvoiceRecord, cfg: dict) -> bool:
    threshold_pct = cfg["exception_types"]["price_variance"]["rule"]["threshold_pct"] / 100
    if record.po_amount == 0:
        return False
    variance_pct = abs(record.invoice_amount - record.po_amount) / record.po_amount
    return variance_pct > threshold_pct


def match_quantity_mismatch(record: POInvoiceRecord) -> bool:
    return record.qty_received != record.qty_ordered


def match_missing_fields(record: POInvoiceRecord, cfg: dict) -> bool:
    required = cfg["exception_types"]["missing_fields"]["rule"]["required_fields"]
    return any(getattr(record, field, None) in (None, "") for field in required)


def match_terms_conflict(record: POInvoiceRecord) -> bool:
    if record.payment_terms_invoice is None or record.payment_terms_contract is None:
        return False
    return record.payment_terms_invoice.strip().lower() != record.payment_terms_contract.strip().lower()


def find_duplicates(records: list[POInvoiceRecord], cfg: dict) -> set[str]:
    """Returns the set of po_numbers that are part of a same-vendor /
    same-amount / within-window duplicate pair, per PRD's duplicate trigger.
    """
    window_days = cfg["exception_types"]["duplicate_po"]["rule"]["window_days"]
    by_vendor: dict[str, list[POInvoiceRecord]] = defaultdict(list)
    for r in records:
        if r.vendor_id:
            by_vendor[r.vendor_id].append(r)

    duplicate_po_numbers: set[str] = set()
    for vendor_records in by_vendor.values():
        vendor_records = sorted(vendor_records, key=lambda r: r.po_date)
        n = len(vendor_records)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = vendor_records[i], vendor_records[j]
                if (b.po_date - a.po_date).days > window_days:
                    break  # sorted by date; no later record can be in-window either
                if abs(a.po_amount - b.po_amount) < 0.01:
                    duplicate_po_numbers.add(a.po_number)
                    duplicate_po_numbers.add(b.po_number)
    return duplicate_po_numbers


def match_all(record: POInvoiceRecord, duplicate_po_numbers: set[str], cfg: dict) -> list[str]:
    """Returns every exception type key that this record's data triggers
    (usually one; occasionally more for ambiguous rows -- see classifier.py
    for how multi-match rows get resolved).
    """
    matches = []
    if match_price_variance(record, cfg):
        matches.append("price_variance")
    if match_quantity_mismatch(record):
        matches.append("quantity_mismatch")
    if record.po_number in duplicate_po_numbers:
        matches.append("duplicate_po")
    if match_missing_fields(record, cfg):
        matches.append("missing_fields")
    if match_terms_conflict(record):
        matches.append("terms_conflict")
    return matches
