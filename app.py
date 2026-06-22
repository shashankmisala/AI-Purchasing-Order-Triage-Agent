"""Streamlit dashboard (FR-7): upload PO + invoice exports, run the triage
pipeline, and explore results with filters, summary stats, email drafts, and
a CSV download.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from src.llm_client import is_available
from src.pipeline import run_triage

st.set_page_config(page_title="PO Exception Triage Agent", page_icon="📋", layout="wide")
st.title("📋 PO Exception Triage Agent")
st.caption(
    "Hybrid rule + LLM agent that classifies PO/invoice exceptions, scores severity, "
    "recommends a disposition, and drafts the follow-up communication."
)

with st.sidebar:
    st.header("Data Source")
    if is_available():
        st.success("Claude API connected — hybrid rule+LLM classification active")
    else:
        st.warning("No ANTHROPIC_API_KEY set — running rule-engine-only fallback")

    use_sample = st.button("📂 Load sample dataset (1,000 rows)")
    st.caption("or upload your own:")
    po_file = st.file_uploader("PO export", type=["csv", "xlsx"], key="po_file")
    invoice_file = st.file_uploader("Invoice export", type=["csv", "xlsx"], key="invoice_file")
    generate_emails = st.checkbox("Generate email drafts", value=True)
    run_clicked = st.button("▶ Run Triage", type="primary")


def _save_upload(uploaded_file, directory: str, name: str) -> str:
    suffix = Path(uploaded_file.name).suffix or ".csv"
    path = str(Path(directory) / f"{name}{suffix}")
    with open(path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return path


po_path = invoice_path = None
upload_dir: tempfile.TemporaryDirectory | None = None
if use_sample:
    po_path, invoice_path = "data/po_export.csv", "data/invoice_export.csv"
elif run_clicked:
    if po_file and invoice_file:
        # Scoped to a directory we explicitly clean up below -- uploaded
        # PO/invoice data is business-confidential and must not linger in
        # the shared OS temp directory after this run finishes. Distinct
        # filenames matter: writing both uploads to the same name in this
        # directory would let the second write silently clobber the first.
        upload_dir = tempfile.TemporaryDirectory(prefix="po-triage-upload-")
        po_path = _save_upload(po_file, upload_dir.name, "po_upload")
        invoice_path = _save_upload(invoice_file, upload_dir.name, "invoice_upload")
    else:
        st.sidebar.error("Upload both a PO file and an Invoice file, or load the sample dataset.")

if po_path and invoice_path:
    progress_bar = st.progress(0.0, text="Starting...")

    def progress_cb(stage: str, frac: float) -> None:
        progress_bar.progress(min(max(frac, 0.0), 1.0), text=stage)

    try:
        outcome = run_triage(po_path, invoice_path, generate_emails=generate_emails, progress_cb=progress_cb)
        st.session_state["outcome"] = outcome
    except Exception as exc:  # ingestion schema errors, etc.
        st.error(f"Triage run failed: {exc}")
    finally:
        if upload_dir is not None:
            upload_dir.cleanup()
    progress_bar.empty()

outcome = st.session_state.get("outcome")
if outcome is None:
    st.info("Load the sample dataset or upload PO + Invoice files from the sidebar to begin.")
    st.stop()

summary = outcome["summary"]
results_df = outcome["results_df"]
results = outcome["results"]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Exceptions", summary.total_exceptions)
col2.metric("HIGH Severity", summary.high_count)
col3.metric("Est. Financial Exposure", f"${summary.estimated_financial_exposure:,.0f}")
col4.metric("Processing Time", f"{summary.processing_seconds:.2f}s")

if summary.validation_errors:
    st.warning(f"{summary.validation_errors} row(s) failed schema validation — see Validation Errors below.")

st.subheader("Filters")
fcol1, fcol2, fcol3 = st.columns(3)
type_options = sorted(results_df["Exception Type"].unique()) if len(results_df) else []
action_options = sorted(results_df["Action"].unique()) if len(results_df) else []
type_filter = fcol1.multiselect("Exception Type", type_options)
sev_filter = fcol2.multiselect("Severity", ["HIGH", "MEDIUM", "LOW"])
action_filter = fcol3.multiselect("Action", action_options)

filtered = results_df.copy()
if type_filter:
    filtered = filtered[filtered["Exception Type"].isin(type_filter)]
if sev_filter:
    filtered = filtered[filtered["Severity"].isin(sev_filter)]
if action_filter:
    filtered = filtered[filtered["Action"].isin(action_filter)]

st.subheader(f"Triage Results ({len(filtered)} of {len(results_df)})")
st.dataframe(filtered, use_container_width=True, height=420)

st.download_button(
    "⬇ Download Full Triage Report (CSV)",
    data=results_df.to_csv(index=False),
    file_name="triage_report.csv",
    mime="text/csv",
)

st.subheader("Email Drafts & Citations")
st.caption(
    "When the LLM disambiguation path is used (requires ANTHROPIC_API_KEY), rationale and "
    "email drafts can cite the actual vendor contract clause, AP policy, or past case "
    "precedent behind the decision -- see docs/RAG_EXPLAINER.md."
)
results_by_po = {r.po_number: r for r in results}
filtered_pos = filtered["PO Number"].tolist()
DISPLAY_CAP = 50
if len(filtered_pos) > DISPLAY_CAP:
    st.caption(f"Showing the first {DISPLAY_CAP} of {len(filtered_pos)} filtered rows. Narrow the filters above to see others.")

for po in filtered_pos[:DISPLAY_CAP]:
    r = results_by_po[po]
    with st.expander(f"{po} — {r.exception_type} ({r.severity.value}) — {r.recommended_action.value}"):
        st.caption(r.rationale)
        if r.citations:
            st.markdown("**Cited sources:** " + ", ".join(f"`{c}`" for c in r.citations))
        if r.email_draft:
            st.text(r.email_draft)
        else:
            st.caption("No communication needed — exception was auto-approved.")

if len(outcome["errors_df"]):
    st.subheader("Validation Errors")
    st.dataframe(outcome["errors_df"], use_container_width=True)
