"""Report generation (FR-5).

Writes the structured CSV triage report (HIGH severity surfaced first per
FR-3) plus a batch summary, and optionally a formatted PDF via Jinja2 +
weasyprint. PDF generation is best-effort: weasyprint needs system libraries
(cairo/pango) that aren't always present, so its absence degrades gracefully
rather than breaking the pipeline (NFR: Portability).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.models import BatchSummary, Severity, TriageResult

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_SEVERITY_SORT = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}

# Excel/Sheets/LibreOffice treat a cell starting with any of these as a
# formula. Vendor-supplied fields (vendor_name, rationale) are untrusted
# input by the time they reach this report, so any leading formula
# character is neutralized with a leading apostrophe before writing -- this
# is the standard CSV/Formula Injection mitigation (OWASP).
_CSV_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value):
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_TRIGGERS):
        return "'" + value
    return value


def results_to_dataframe(results: list[TriageResult]) -> pd.DataFrame:
    rows = [
        {
            "PO Number": _csv_safe(r.po_number),
            "Vendor": _csv_safe(r.vendor_name or r.vendor_id),
            "Exception Type": r.exception_type,
            "Severity": r.severity.value,
            "Score": r.urgency_score,
            "Action": r.recommended_action.value,
            "Rationale": _csv_safe(r.rationale),
            "Confidence": r.confidence,
            "Classification Method": r.classification_method.value,
            "Financial Variance": r.financial_variance,
            "Needs Human Review": r.needs_human_review,
            "Citations": _csv_safe("; ".join(r.citations)) if r.citations else "",
        }
        for r in sorted(results, key=lambda r: (_SEVERITY_SORT[r.severity], -r.urgency_score))
    ]
    return pd.DataFrame(rows)


def build_summary(results: list[TriageResult], validation_errors: int, processing_seconds: float) -> BatchSummary:
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    exposure = 0.0
    high_count = 0
    for r in results:
        by_type[r.exception_type] = by_type.get(r.exception_type, 0) + 1
        by_severity[r.severity.value] = by_severity.get(r.severity.value, 0) + 1
        exposure += r.financial_variance
        if r.severity == Severity.HIGH:
            high_count += 1
    return BatchSummary(
        total_exceptions=len(results),
        by_type=by_type,
        by_severity=by_severity,
        estimated_financial_exposure=round(exposure, 2),
        high_count=high_count,
        validation_errors=validation_errors,
        processing_seconds=round(processing_seconds, 2),
    )


def write_csv_report(results: list[TriageResult], path: str | Path) -> Path:
    path = Path(path)
    results_to_dataframe(results).to_csv(path, index=False)
    return path


def _no_remote_fetch(url, timeout=10, **kwargs):
    """The report template is fully self-contained (inline CSS only), so any
    resource fetch attempt -- e.g. an <img>/@import URL smuggled in via an
    unescaped vendor_name field -- is an injection, not a legitimate need.
    Blocking it outright closes the SSRF vector without losing functionality.
    """
    raise ValueError(f"Remote resource fetching is disabled for PDF report generation (blocked: {url})")


def write_pdf_report(summary: BatchSummary, results: list[TriageResult], path: str | Path) -> bool:
    """Returns True if the PDF was written, False if weasyprint isn't installed."""
    try:
        from weasyprint import HTML
    except (ImportError, OSError):
        return False

    # autoescape is mandatory here: result fields like vendor_name originate
    # from uploaded PO/invoice files (untrusted input) and are rendered into
    # this HTML before being converted to PDF.
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=select_autoescape(["html"]))
    template = env.get_template("report.html")
    html = template.render(
        summary=summary,
        results=sorted(results, key=lambda r: (_SEVERITY_SORT[r.severity], -r.urgency_score)),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    HTML(string=html, url_fetcher=_no_remote_fetch).write_pdf(str(path))
    return True
