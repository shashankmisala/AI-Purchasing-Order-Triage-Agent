# PO Exception Triage Agent

**🔗 Live demo:** *[add your Render URL here once deployed — see `docs/CLIENT_ENGAGEMENT.md` for the deploy runbook]*

A Tech Consultant Intern engagement deliverable: an AI agent that automates Purchase Order
(PO) exception triage for **Meridian Industrial Supply Co.** (fictional client, built for
portfolio purposes) — a mid-market distributor processing 150-250 procurement exceptions a
day across ~200 vendors. The agent ingests PO + invoice data, classifies each exception
(price variance, quantity mismatch, duplicate PO, missing fields, terms conflict), retrieves
the relevant vendor contract clause / AP policy / past precedent to ground its reasoning,
scores severity, recommends a disposition, drafts the follow-up communication, and produces
an auditable triage report — turning a ~4-minute manual review into a sub-second automated
one with a citation a human reviewer can actually verify.

Full engagement writeup (situation/task/action/result + roadmap): **[`docs/CLIENT_ENGAGEMENT.md`](docs/CLIENT_ENGAGEMENT.md)**
How the RAG layer works and why it matters for supply chain specifically: **[`docs/RAG_EXPLAINER.md`](docs/RAG_EXPLAINER.md)**
Original requirements doc: [`PO_Exception_Triage_Agent_PRD.docx`](./PO_Exception_Triage_Agent_PRD.docx)

## How it works

A **hybrid rule + LLM + RAG pipeline**, designed around one cost/risk principle: only spend
an API call where a deterministic rule genuinely can't decide, and never trust a model's
self-reported confidence or citations without an independent check.

1. **Ingestion** (`src/ingestion.py`) — reads PO + invoice CSV/XLSX, merges on PO Number,
   validates against a Pydantic schema, logs malformed rows without failing the batch.
2. **Rule engine** (`src/rules.py`) — deterministic checks for all five exception types.
   Handles the clear-cut majority of rows without an API call.
3. **Retrieval** (`src/rag/`) — for genuinely ambiguous rows (matching more than one
   exception type), retrieves that vendor's actual contract clauses plus the AP policy manual
   and past case precedent — local TF-IDF search, no API cost — so the next step can ground
   its answer in a real document instead of guessing from a flat CSV row. See
   `docs/RAG_EXPLAINER.md` for the full design and a worked example.
4. **Classifier** (`src/classifier.py`) — ambiguous rows go to **Claude**
   (`claude-sonnet-4-6`) along with the retrieved context. If no API key is configured, or the
   call fails, it falls back to a deterministic "highest severity wins" rule — the app always
   runs, with or without credentials. Every model output (classification, confidence, cited
   sources) is cross-checked against an independent deterministic baseline before being
   trusted; nothing the model self-reports is taken at face value.
5. **Scoring** (`src/scorer.py`) — a 1–10 urgency score from financial variance, exception
   type, and vendor payment history, mapped to HIGH/MEDIUM/LOW.
6. **Recommendation** (`src/recommender.py`) — Approve / Escalate to Manager / Reject Invoice
   / Request Vendor Clarification, with a rationale. Low-confidence classifications are always
   routed to human review.
7. **Email drafting** (`src/email_drafter.py`) — a plain-English message per exception (vendor
   email for Clarify/Reject, internal note for Escalate, none needed for Approve), able to
   cite the same verified contract/policy passage behind the decision. Uses Claude when
   available, a Jinja2 template otherwise.
8. **Reporting** (`src/report.py`) — CSV triage report (HIGH severity first, citations
   included) + batch summary + optional PDF.
9. **Dashboard** (`app.py`) — Streamlit UI to upload files (or load the sample dataset), watch
   progress, filter results, read email drafts and citations, and download the report.

New exception types can be added by editing `config/exception_types.yaml` alone. New vendor
contracts / policy updates can be added by dropping a Markdown file into `knowledge_base/`.

## Security

A `/cso`-style security review was run against this codebase before it was considered
deployable. Four real, exploitable findings were identified, fixed, and independently
re-verified with executable proof-of-concept tests (not just code review):

1. **HTML injection / SSRF** in the PDF report's Jinja2 template (unescaped vendor fields
   reaching a server-side HTML-to-PDF renderer) — fixed with `autoescape` + a blocked
   `url_fetcher`.
2. **Prompt injection defeating the LLM confidence gate** — a vendor-controlled field could
   forge a high self-reported confidence to skip the mandatory human-review safety net — fixed
   by requiring the model's suggested action to agree with an independently-computed
   deterministic baseline before trusting it.
3. **CSV formula injection** in the downloadable report — fixed by neutralizing leading
   formula-trigger characters before writing.
4. **Unbounded temp-file retention** of uploaded PO/invoice data — fixed with a cleaned-up
   `TemporaryDirectory`.

The same "never trust a model's self-report" principle was extended to the RAG layer's
citations: every citation a model claims is cross-checked against what was actually retrieved
and shown to it, and anything fabricated is silently dropped (see `docs/RAG_EXPLAINER.md`).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional — enable the LLM + RAG disambiguation path:

```bash
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

Without a key, the agent runs entirely on the rule engine (no degraded experience — this
dataset's exceptions are nearly all unambiguous by construction; see Benchmarks below). **The
public live demo deliberately runs without a key** — see "Deployment" below for why.

## Generate the synthetic dataset

```bash
python -m src.generate_dataset
```

Writes `data/po_export.csv`, `data/invoice_export.csv`, and `data/ground_truth.csv` — 1,000
PO exceptions across 200 vendors, matching the original PRD's distribution (Price Variance
35%, Quantity Mismatch 25%, Duplicate PO 15%, Missing Fields 15%, Terms Conflict 10%). Fifteen
of those 200 vendors have a synthetic contract on file in `knowledge_base/vendor_contracts/`
for the RAG layer to retrieve.

## Run it

**Dashboard:**

```bash
streamlit run app.py
```

Click "Load sample dataset" in the sidebar, or upload your own PO/invoice CSVs.

**Command line:**

```bash
python -m src.pipeline data/po_export.csv data/invoice_export.csv --out data/triage_report.csv --pdf data/triage_report.pdf
```

**Benchmark against the labeled dataset:**

```bash
python benchmark.py
```

Prints classification accuracy, a confusion matrix, per-class precision/recall, and timing —
validating the original success metrics (>88% accuracy, <10s/exception, <5min/200-exception
batch). Currently: **100% accuracy, ~0.04ms/exception** on the rule-only path.

## Deployment

Deployed to [Render](https://render.com) via `render.yaml` (free tier). The public deployment
runs **rule-engine-only by default** — no `ANTHROPIC_API_KEY` is set on the live instance —
so nobody can run up an API bill or abuse the public URL. The full hybrid LLM + RAG path is
fully functional and demoed locally (run it yourself with a key, or see `docs/RAG_EXPLAINER.md`
for a worked example).

To deploy your own copy: push this repo to GitHub/GitLab, connect it in Render's dashboard,
and let it pick up `render.yaml`. Optionally add `ANTHROPIC_API_KEY` as a Render environment
variable if you want your own deployment to run the full hybrid path live (be aware this
means anyone with the URL can trigger billed API calls).

## Project layout

```
docs/CLIENT_ENGAGEMENT.md     consulting-engagement writeup (situation/task/action/result)
docs/RAG_EXPLAINER.md         how the RAG layer works, with a worked example
knowledge_base/                vendor contracts, AP policy manual, resolved-exception precedent
config/exception_types.yaml   exception taxonomy, thresholds, severity bands (edit to extend)
src/models.py                 Pydantic schemas
src/generate_dataset.py       synthetic dataset generator
src/ingestion.py              CSV/XLSX parsing + schema validation
src/rules.py                  deterministic exception detection
src/rag/ingest.py             knowledge-base chunking + TF-IDF indexing
src/rag/retriever.py          vendor-filtered, cited retrieval
src/llm_client.py             Claude API wrapper (classification + email drafting)
src/classifier.py             hybrid rule/LLM/RAG orchestration
src/scorer.py                 severity + urgency scoring
src/recommender.py            action recommendation
src/email_drafter.py          email draft generation
src/report.py                 CSV/PDF report + batch summary
src/pipeline.py               end-to-end orchestration (shared by CLI + dashboard)
app.py                        Streamlit dashboard
benchmark.py                  accuracy/timing benchmark vs. ground truth
render.yaml                   Render deployment config
```

## Notes on scope (v1.0)

Out of scope for this phase: direct ERP integration, automated email *sending* (drafts only —
a human must send), multi-currency support, real-time/webhook triggers, auth/RBAC, and
extending RAG retrieval into the rule-classified (non-ambiguous) path. All documented as
recommended next phases in `docs/CLIENT_ENGAGEMENT.md`.

The original PRD's section 7.2 severity distribution (HIGH 25% / MEDIUM 45% / LOW 30%)
describes an aspirational dataset-level target; the scorer instead derives severity
deterministically from financial impact, exception type, and vendor history, which is what an
auditable real-world scorer should do. On the generated dataset this skews more HIGH-heavy
(Price Variance and Quantity Mismatch are HIGH by definition) — documented here rather than
forcing an artificial distribution.
