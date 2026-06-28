# PO Exception Triage Agent

> A hybrid rule-engine + LLM + RAG AI agent that automates Purchase Order exception triage — classifying exceptions, scoring severity, recommending dispositions, and drafting follow-up emails — turning a ~4-minute manual review into a sub-second automated one with a verifiable audit trail.

**Live demo:** _[Add your Render URL here — see `docs/CLIENT_ENGAGEMENT.md` for the deploy runbook]_

---

## What It Does

Accounts Payable teams at mid-market distributors typically process 150–250 PO/invoice exceptions per day — price variances, quantity mismatches, duplicate orders, missing fields, and payment terms conflicts. Each one takes ~4 minutes of analyst time to review, route, and communicate. The math adds up fast.

This agent automates that entire workflow:

1. **Ingests** PO and invoice exports (CSV or XLSX), merges them on PO Number, and validates each row against a strict schema — routing malformed rows to an error log without failing the batch.
2. **Classifies** each exception into one of five types using a deterministic rule engine that handles the unambiguous majority of rows without any API call.
3. **Disambiguates** genuinely ambiguous rows (where more than one exception type applies) by first retrieving the relevant vendor contract, AP policy manual, and past case precedent from a local knowledge base, then passing all of it to **Claude** (`claude-sonnet-4-6`) for a grounded decision — not a guess from a flat CSV row.
4. **Scores** each exception on a 1–10 urgency scale derived from financial variance, exception type, and vendor payment history.
5. **Recommends** a disposition: Approve, Escalate to Manager, Reject Invoice, or Request Vendor Clarification — with a written rationale and a verified source citation.
6. **Drafts** the follow-up email per exception (vendor email for Clarify/Reject, internal note for Escalate, nothing needed for Approve).
7. **Reports** results in a filterable Streamlit dashboard and a downloadable CSV triage report (HIGH severity first).

**Without an API key**, the agent falls back to the deterministic rule engine only — it always runs, with no degraded user experience for this dataset where exceptions are nearly all unambiguous by construction.

---

## Architecture

```
PO export + Invoice export
         │
         ▼
   src/ingestion.py          — CSV/XLSX merge + Pydantic schema validation
         │
         ▼
   src/rules.py              — Deterministic checks for all 5 exception types
         │
    ┌────┴────┐
    │         │
  1 match  2+ matches (ambiguous)
    │         │
    │    src/rag/retriever.py — TF-IDF retrieval: vendor contract + AP policy + precedent
    │         │
    │    src/llm_client.py   — Claude call with retrieved context (or deterministic fallback)
    │         │
    └────┬────┘
         │
         ▼
   src/scorer.py             — 1–10 urgency score → HIGH / MEDIUM / LOW severity
         │
         ▼
   src/recommender.py        — Action recommendation + rationale
         │
         ▼
   src/email_drafter.py      — Email draft (LLM or Jinja2 template fallback)
         │
         ▼
   src/report.py             — CSV report + batch summary + optional PDF
         │
         ▼
   app.py (Streamlit)        — Dashboard: upload, filter, inspect, download
```

### The hybrid design principle

Rules run first. The LLM is only called when the rule engine produces a genuinely ambiguous result (multiple exception types match). This keeps API cost low and bounded — not a model call on every row. Every model output (classification, confidence, cited sources) is cross-checked against an independently-computed deterministic baseline before being trusted; nothing the model self-reports is taken at face value.

---

## Exception Types

Configured in `config/exception_types.yaml` — new types can be added without touching code.

| Type | Severity | Description |
|---|---|---|
| Price Variance | HIGH | Invoice price differs from PO by >0.5% |
| Quantity Mismatch | HIGH | Goods received doesn't match quantity ordered |
| Duplicate PO | MEDIUM | Same vendor, amount, and date within a 5-day window |
| Missing Fields | MEDIUM | Required field (vendor ID, GL code, delivery date) is blank |
| Terms Conflict | LOW | Invoice payment terms differ from contracted terms |

---

## RAG Layer

For ambiguous rows, the agent retrieves relevant passages from a local knowledge base before calling the LLM:

```
knowledge_base/
├── vendor_contracts/        — One Markdown file per vendor with a contract on file
├── policies/                — AP policy manual (always retrieved for all vendors)
└── precedents/              — Resolved-exception log for consistency with past decisions
```

Retrieval uses TF-IDF + cosine similarity (via scikit-learn), with a vendor-filter step that runs before similarity ranking — so results are always scoped to the right vendor's contract, not the lexically closest contract from a random vendor.

The result: rationales that cite actual contract clauses a human reviewer can go verify, not generic explanations.

> See `docs/RAG_EXPLAINER.md` for the full design, a worked example with real similarity scores, and the deliberate engineering tradeoffs (TF-IDF vs. dense embeddings, free-tier RAM constraints, the upgrade path).

---


## Project Layout

```
app.py                              Streamlit dashboard
src/
  models.py                         Pydantic schemas (POInvoiceRecord, TriageResult, etc.)
  ingestion.py                      CSV/XLSX parsing + schema validation
  rules.py                          Deterministic exception detection
  classifier.py                     Hybrid rule / LLM / RAG orchestration
  llm_client.py                     Claude API wrapper (classify + email draft)
  scorer.py                         Severity + urgency scoring
  recommender.py                    Action recommendation
  email_drafter.py                  Email draft generation
  report.py                         CSV / PDF report + batch summary
  pipeline.py                       End-to-end orchestration (shared by CLI + dashboard)
  generate_dataset.py               Synthetic dataset generator
  rag/
    ingest.py                       Knowledge-base chunking + TF-IDF indexing
    retriever.py                    Vendor-filtered, cited retrieval
config/
  exception_types.yaml              Exception taxonomy, thresholds, severity bands
knowledge_base/
  vendor_contracts/                 Per-vendor contract Markdown files
  policies/                         AP policy manual
  precedents/                       Resolved-exception log
data/
  po_export.csv                     Sample PO export (1,000 rows)
  invoice_export.csv                Sample invoice export
  ground_truth.csv                  Labeled ground truth for benchmarking
templates/
  email.txt                         Jinja2 email template (fallback when no API key)
  report.html                       Jinja2 HTML report template
docs/
  CLIENT_ENGAGEMENT.md              Engagement writeup (situation / task / action / result)
  RAG_EXPLAINER.md                  RAG design, worked example, and tradeoffs
benchmark.py                        Accuracy + timing benchmark vs. ground truth
render.yaml                         Render deployment config
```

---

## Tech Stack

- **Python 3.11+**
- **Streamlit** — dashboard UI
- **Claude (`claude-sonnet-4-6`)** via Anthropic API — LLM disambiguation + email drafting
- **Pydantic v2** — schema validation
- **scikit-learn** — TF-IDF vectorization for RAG retrieval
- **pandas** — data ingestion and reporting
- **Jinja2** — email + PDF templates
- **WeasyPrint** — optional PDF report generation

---

## Scope Notes (v1.0)

Out of scope for this phase: direct ERP integration, automated email *sending* (drafts only — a human must send), multi-currency support, real-time/webhook triggers, auth/RBAC, and extending RAG retrieval into the rule-classified (non-ambiguous) path. All documented as recommended next phases in `docs/CLIENT_ENGAGEMENT.md`.
