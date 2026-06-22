"""Benchmarks the classifier against the labeled synthetic dataset (PRD section 8).

Reports classification accuracy, a confusion matrix, per-class precision/
recall, and timing -- validating the PRD's success metrics:
  - Classification accuracy > 88%
  - Triage time per exception < 10 sec
  - End-to-end batch processing < 5 min / 200 exceptions

Runs against whatever's in data/ (regenerate with `python -m src.generate_dataset`
if needed). Uses the LLM path automatically when ANTHROPIC_API_KEY is set;
otherwise runs purely on the rule engine.
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix

from src import rules
from src.classifier import classify_batch
from src.ingestion import ingest
from src.llm_client import is_available

DATA_DIR = Path(__file__).resolve().parent / "data"


def main() -> None:
    records, errors = ingest(DATA_DIR / "po_export.csv", DATA_DIR / "invoice_export.csv")
    gt_path = DATA_DIR / "ground_truth.csv"
    if not gt_path.exists():
        raise SystemExit("No ground_truth.csv found -- run `python -m src.generate_dataset` first.")
    ground_truth = pd.read_csv(gt_path).set_index("po_number")["exception_type"].to_dict()

    cfg = rules.load_config()
    label_by_key = {k: v["label"] for k, v in cfg["exception_types"].items()}

    print(f"LLM path: {'ENABLED (ANTHROPIC_API_KEY set)' if is_available() else 'DISABLED -- rule-engine-only fallback'}")
    print(f"Records ingested: {len(records)} (validation errors: {len(errors)})\n")

    t0 = time.time()
    results = classify_batch(records, cfg)
    elapsed = time.time() - t0

    y_true, y_pred = [], []
    for r in results:
        expected_key = ground_truth.get(r.po_number)
        if expected_key is None:
            continue
        y_true.append(label_by_key[expected_key])
        y_pred.append(r.exception_type)

    accuracy = sum(t == p for t, p in zip(y_true, y_pred)) / len(y_true) if y_true else 0.0
    per_exception_ms = (elapsed / len(records)) * 1000 if records else 0.0
    batch_200_equiv = (elapsed / len(records)) * 200 if records else 0.0

    print("=== Accuracy (target: >88%) ===")
    print(f"  {accuracy:.4f} over {len(y_true)} labeled rows\n")

    print("=== Timing (target: <10s/exception, <5min/200-exception batch) ===")
    print(f"  Total batch time:        {elapsed:.3f}s for {len(records)} records")
    print(f"  Per-exception:           {per_exception_ms:.2f} ms")
    print(f"  Equivalent 200-batch:    {batch_200_equiv:.2f}s\n")

    method_counts: dict[str, int] = {}
    for r in results:
        method_counts[r.classification_method.value] = method_counts.get(r.classification_method.value, 0) + 1
    print("=== Classification method breakdown ===")
    for method, count in sorted(method_counts.items()):
        print(f"  {method:14s}: {count} ({count/len(results)*100:.1f}%)")
    print()

    review_flagged = sum(1 for r in results if r.needs_human_review)
    print(f"=== Human review flagged (confidence < {cfg['human_review_confidence_threshold']}) ===")
    print(f"  {review_flagged} / {len(results)} ({review_flagged/len(results)*100:.1f}%)\n")

    labels = sorted(set(y_true) | set(y_pred))
    print("=== Confusion matrix (rows=actual, cols=predicted) ===")
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    print(pd.DataFrame(cm, index=labels, columns=labels))
    print()

    print("=== Per-class precision / recall / F1 ===")
    print(classification_report(y_true, y_pred, labels=labels, zero_division=0))


if __name__ == "__main__":
    main()
