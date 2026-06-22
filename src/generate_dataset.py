"""Synthetic PO + invoice dataset generator (PRD section 7).

Produces three CSVs in data/:
  - po_export.csv       (the PO-side ERP export)
  - invoice_export.csv  (the invoice-side AP export, joined on PO Number)
  - ground_truth.csv    (canonical exception_type label per PO, for benchmarking)

Real PO/invoice data is proprietary, so the dataset is built deliberately: each
row is constructed to trigger exactly one (occasionally two, for realism) of
the five exception types, with financial magnitudes and vendor mix drawn from
the ranges specified in the PRD. A fixed seed keeps the dataset reproducible
across runs.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from faker import Faker

SEED = 42
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

INDUSTRIES = ["Automotive Parts", "Consumer Goods", "Industrial Equipment"]
CONTRACT_TERMS_POOL = ["Net 30", "Net 45", "Net 60", "2/10 Net 30"]

# PRD 3.1 exception distribution (must sum to TOTAL_RECORDS).
TOTAL_RECORDS = 1000
TYPE_COUNTS = {
    "price_variance": 350,
    "quantity_mismatch": 250,
    "duplicate_po": 150,   # generated as 75 pairs
    "missing_fields": 150,
    "terms_conflict": 100,
}
assert sum(TYPE_COUNTS.values()) == TOTAL_RECORDS

NUM_VENDORS = 200
REFERENCE_DATE = date(2026, 6, 1)


def _make_vendors(fake: Faker, rng: random.Random) -> list[dict]:
    vendors = []
    for i in range(NUM_VENDORS):
        history_roll = rng.random()
        if history_roll < 0.75:
            history_flag = "good"
        elif history_roll < 0.93:
            history_flag = "late"
        else:
            history_flag = "disputed"
        vendors.append(
            {
                "vendor_id": f"V-{i + 1:04d}",
                "vendor_name": fake.company(),
                "industry": rng.choice(INDUSTRIES),
                "contract_terms": rng.choice(CONTRACT_TERMS_POOL),
                "vendor_payment_history_flag": history_flag,
            }
        )
    return vendors


def _random_date(rng: random.Random, days_back: int = 120) -> date:
    return REFERENCE_DATE - timedelta(days=rng.randint(0, days_back))


def _base_row(po_num: str, vendor: dict, rng: random.Random) -> dict:
    """A 'clean' row with no exception triggers; callers mutate it to inject one."""
    po_amount = round(rng.uniform(500, 2_500_000), 2)
    qty_ordered = rng.randint(1, 500)
    po_date = _random_date(rng)
    return {
        "po_number": po_num,
        "vendor_id": vendor["vendor_id"],
        "vendor_name": vendor["vendor_name"],
        "industry": vendor["industry"],
        "po_amount": po_amount,
        "invoice_amount": po_amount,
        "qty_ordered": qty_ordered,
        "qty_received": qty_ordered,
        "gl_code": f"GL-{rng.randint(1000, 9999)}",
        "payment_terms_invoice": vendor["contract_terms"],
        "payment_terms_contract": vendor["contract_terms"],
        "po_date": po_date,
        "invoice_date": po_date + timedelta(days=rng.randint(1, 10)),
        "delivery_date": po_date + timedelta(days=rng.randint(1, 14)),
        "vendor_payment_history_flag": vendor["vendor_payment_history_flag"],
    }


def _inject_price_variance(row: dict, rng: random.Random) -> dict:
    variance_pct = rng.uniform(0.006, 0.20)  # >0.5% threshold, up to 20%
    variance_amount = max(10.0, min(150_000.0, row["po_amount"] * variance_pct))
    sign = rng.choice([1, -1])
    row["invoice_amount"] = round(row["po_amount"] + sign * variance_amount, 2)
    # ~6% of these are also ambiguous (missing GL code) to exercise the
    # hybrid LLM disambiguation path; highest-severity (price variance, HIGH)
    # still wins per FR-2, so the ground-truth label is unaffected.
    if rng.random() < 0.06:
        row["gl_code"] = None
    return row


def _inject_quantity_mismatch(row: dict, rng: random.Random) -> dict:
    delta = rng.randint(1, max(1, int(row["qty_ordered"] * 0.3)))
    sign = rng.choice([1, -1])
    row["qty_received"] = max(0, row["qty_ordered"] + sign * delta)
    if rng.random() < 0.06:
        row["gl_code"] = None
    return row


def _inject_missing_fields(row: dict, rng: random.Random) -> dict:
    field = rng.choice(["vendor_id", "gl_code", "delivery_date"])
    row[field] = None
    return row


def _inject_terms_conflict(row: dict, rng: random.Random) -> dict:
    alt_terms = [t for t in CONTRACT_TERMS_POOL if t != row["payment_terms_contract"]]
    row["payment_terms_invoice"] = rng.choice(alt_terms)
    return row


def generate(seed: int = SEED) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    fake = Faker()
    Faker.seed(seed)
    rng = random.Random(seed)

    vendors = _make_vendors(fake, rng)

    rows: list[dict] = []
    ground_truth: list[dict] = []
    po_seq = 1

    def next_po_number() -> str:
        nonlocal po_seq
        n = f"PO-{po_seq:06d}"
        po_seq += 1
        return n

    # --- single-type exceptions -------------------------------------------------
    for kind, injector in (
        ("price_variance", _inject_price_variance),
        ("quantity_mismatch", _inject_quantity_mismatch),
        ("missing_fields", _inject_missing_fields),
        ("terms_conflict", _inject_terms_conflict),
    ):
        for _ in range(TYPE_COUNTS[kind]):
            vendor = rng.choice(vendors)
            po_num = next_po_number()
            row = _base_row(po_num, vendor, rng)
            row = injector(row, rng)
            rows.append(row)
            ground_truth.append({"po_number": po_num, "exception_type": kind})

    # --- duplicate PO pairs -------------------------------------------------------
    num_pairs = TYPE_COUNTS["duplicate_po"] // 2
    for _ in range(num_pairs):
        vendor = rng.choice(vendors)
        po_a = next_po_number()
        base = _base_row(po_a, vendor, rng)
        rows.append(base)
        ground_truth.append({"po_number": po_a, "exception_type": "duplicate_po"})

        po_b = next_po_number()
        dup = dict(base)
        dup["po_number"] = po_b
        offset = rng.randint(0, 4)  # within the 5-day duplicate window
        dup["po_date"] = base["po_date"] + timedelta(days=offset)
        dup["invoice_date"] = dup["po_date"] + timedelta(days=rng.randint(1, 10))
        dup["delivery_date"] = dup["po_date"] + timedelta(days=rng.randint(1, 14))
        rows.append(dup)
        ground_truth.append({"po_number": po_b, "exception_type": "duplicate_po"})

    rng.shuffle(rows)
    df = pd.DataFrame(rows)
    gt_df = pd.DataFrame(ground_truth)

    po_cols = [
        "po_number", "vendor_id", "vendor_name", "industry", "po_amount",
        "qty_ordered", "gl_code", "payment_terms_contract", "po_date",
        "vendor_payment_history_flag",
    ]
    invoice_cols = [
        "po_number", "invoice_amount", "qty_received", "payment_terms_invoice",
        "invoice_date", "delivery_date",
    ]
    po_df = df[po_cols].rename(columns={
        "po_amount": "PO Amount", "qty_ordered": "Quantity Ordered",
        "gl_code": "GL Code", "payment_terms_contract": "Payment Terms",
        "po_date": "PO Date", "vendor_id": "Vendor ID", "vendor_name": "Vendor Name",
        "industry": "Industry", "po_number": "PO Number",
        "vendor_payment_history_flag": "Vendor Payment History",
    })
    invoice_df = df[invoice_cols].rename(columns={
        "invoice_amount": "Invoice Amount", "qty_received": "Quantity Received",
        "payment_terms_invoice": "Payment Terms", "invoice_date": "Invoice Date",
        "delivery_date": "Delivery Date", "po_number": "PO Number",
    })

    return po_df, invoice_df, gt_df


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    po_df, invoice_df, gt_df = generate()
    po_df.to_csv(DATA_DIR / "po_export.csv", index=False)
    invoice_df.to_csv(DATA_DIR / "invoice_export.csv", index=False)
    gt_df.to_csv(DATA_DIR / "ground_truth.csv", index=False)
    print(f"Wrote {len(po_df)} PO rows -> {DATA_DIR / 'po_export.csv'}")
    print(f"Wrote {len(invoice_df)} invoice rows -> {DATA_DIR / 'invoice_export.csv'}")
    print(f"Wrote {len(gt_df)} ground-truth labels -> {DATA_DIR / 'ground_truth.csv'}")
    print("\nException type distribution:")
    print(gt_df["exception_type"].value_counts())


if __name__ == "__main__":
    main()
