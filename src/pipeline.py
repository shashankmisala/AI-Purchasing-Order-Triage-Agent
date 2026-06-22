"""End-to-end orchestration: ingestion -> classify -> score -> recommend ->
email -> report (PRD 4.2 data flow). Shared by both the CLI entry point below
and the Streamlit dashboard (app.py), so the two surfaces never drift.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Callable, Optional

from src import email_drafter, ingestion, report, rules
from src.classifier import classify_record

ProgressCallback = Callable[[str, float], None]


def run_triage(
    po_path: str | Path,
    invoice_path: str | Path,
    generate_emails: bool = True,
    progress_cb: Optional[ProgressCallback] = None,
) -> dict:
    def progress(stage: str, frac: float) -> None:
        if progress_cb:
            progress_cb(stage, frac)

    t0 = time.time()
    progress("Ingesting files", 0.0)
    records, error_df = ingestion.ingest(po_path, invoice_path)

    progress("Classifying exceptions", 0.1)
    cfg = rules.load_config()
    duplicate_po_numbers = rules.find_duplicates(records, cfg)

    results = []
    rec_by_po = {}
    n = len(records)
    step = max(1, n // 20)
    for i, record in enumerate(records):
        rec_by_po[record.po_number] = record
        result = classify_record(record, duplicate_po_numbers, cfg)
        if result is not None:
            results.append(result)
        if i % step == 0:
            progress("Classifying exceptions", 0.1 + 0.5 * (i / max(1, n)))

    if generate_emails and results:
        progress("Drafting emails", 0.6)
        m = len(results)
        step = max(1, m // 20)
        for i, r in enumerate(results):
            r.email_draft = email_drafter.draft_email(r, rec_by_po[r.po_number])
            if i % step == 0:
                progress("Drafting emails", 0.6 + 0.3 * (i / m))

    elapsed = time.time() - t0
    progress("Building report", 0.95)
    summary = report.build_summary(results, len(error_df), elapsed)
    results_df = report.results_to_dataframe(results)
    progress("Done", 1.0)

    return {
        "results": results,
        "results_df": results_df,
        "summary": summary,
        "errors_df": error_df,
        "elapsed_seconds": elapsed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PO exception triage pipeline from the command line.")
    parser.add_argument("po_file")
    parser.add_argument("invoice_file")
    parser.add_argument("--out", default="data/triage_report.csv", help="CSV output path")
    parser.add_argument("--pdf", default=None, help="Optional PDF summary output path")
    parser.add_argument("--no-emails", action="store_true", help="Skip email draft generation (faster, no LLM calls for emails)")
    args = parser.parse_args()

    def cli_progress(stage: str, frac: float) -> None:
        print(f"[{frac*100:5.1f}%] {stage}")

    outcome = run_triage(args.po_file, args.invoice_file, generate_emails=not args.no_emails, progress_cb=cli_progress)
    report.write_csv_report(outcome["results"], args.out)
    print(f"\nWrote triage report -> {args.out}")
    print(outcome["summary"])

    if args.pdf:
        written = report.write_pdf_report(outcome["summary"], outcome["results"], args.pdf)
        print(f"PDF written -> {args.pdf}" if written else "PDF skipped (weasyprint not installed)")

    if len(outcome["errors_df"]):
        print(f"\n{len(outcome['errors_df'])} rows failed validation -- see error log:")
        print(outcome["errors_df"])


if __name__ == "__main__":
    main()
