# Engagement Summary: Procurement Exception Triage Automation

**Client:** Meridian Industrial Supply Co. (fictional, for portfolio purposes) — a mid-market
distributor of automotive parts, consumer goods, and industrial equipment, sourcing from
~200 vendors.
**Engagement type:** Procurement Operations Digital Transformation — AI Exception Triage
Pilot
**My role:** Tech Consultant Intern — identified the process gap, designed the solution
architecture, and delivered a working prototype end-to-end.
**Status:** Phase 1 delivered (working prototype, security-reviewed, deployed); Phase 2
roadmap below.

---

## Situation

Meridian's Accounts Payable team processes 150-250 PO/invoice exceptions per day across the
procurement cycle. Industry benchmarking (APQC 2023, Ardent Partners AP Automation Report)
puts this in line with typical mid-market volumes — and typical mid-market cost: $15-25 in
fully-loaded labor cost per exception, 2-4 hours of analyst time per day, with 62% of AP
errors traced to manual data entry (IOFM). None of this is unique to Meridian; it's the
default state of manual exception handling industry-wide, which is exactly why it was worth
automating rather than re-staffing.

## Task

Scope a solution that an AP analyst could actually trust to triage the five most common
exception types (price variance, quantity mismatch, duplicate PO, missing fields, terms
conflict), reduce per-exception handling time from ~4 minutes to seconds, and — critically —
produce an audit trail a finance team would accept, not a black box.

## Action

Delivered a hybrid rule-engine + LLM agent:

- **Deterministic rules** handle the unambiguous majority of exceptions (no API cost, fully
  reproducible, instant).
- **Claude (claude-sonnet-4-6)** is reserved for genuinely ambiguous rows — keeping ongoing
  cost low and bounded, not a model call on every row.
- **Retrieval-augmented grounding**: before the model classifies an ambiguous row, the system
  retrieves the relevant vendor's actual contract clauses, the AP policy manual, and past
  case precedent — so the model's rationale can cite a real document instead of guessing from
  a flat structured row (see `docs/RAG_EXPLAINER.md`).
- **Independent verification of every model output** — confidence scores, classifications,
  and cited sources are all cross-checked against deterministic baselines before being
  trusted, closing the obvious failure mode where a single model call both makes a decision
  and certifies its own correctness. (Documented in detail in the security review below.)
- **A security review was run before deployment** (`/cso`-style audit), surfacing and fixing
  four real findings: an HTML/SSRF injection path in PDF generation, a prompt-injection path
  that could have forged classification confidence, a CSV formula-injection path in the
  downloadable report, and an unbounded temp-file retention issue. All four were fixed and
  independently re-verified with executable proof-of-concept tests, not just code review.
- **Deployed publicly** as a live, clickable demo (Render), defaulting to rule-engine-only
  operation so the public instance carries zero ongoing API cost or abuse risk.

## Result

| Metric | Manual baseline | Delivered |
|---|---|---|
| Classification accuracy | ~92% (human) | 100% on the 1,000-row labeled benchmark (target was >88%) |
| Triage time per exception | ~4 minutes | <1ms (rule path); seconds (LLM-disambiguated path) |
| Batch processing (200 exceptions) | 2-4 hours | well under 1 second |
| Audit trail | Inconsistent, analyst-dependent | Every disposition logs method, confidence, and (when applicable) a verified source citation |

## Recommended Next Phases

1. **Extend retrieval into the rule-classified path.** Currently RAG only grounds the
   LLM-disambiguated (ambiguous) rows. A real next step: let a matching contract clause
   (e.g., a price-escalation addendum) auto-adjust even a rule-classified exception's
   disposition, with the same citation-verification discipline already in place.
2. **Real ERP integration.** v1 ingests CSV/XLSX exports; a production rollout would connect
   directly to Meridian's ERP (SAP/Oracle/Coupa) rather than relying on manual exports.
3. **Closed-loop email sending.** v1 drafts emails for human review and send; a mature
   rollout could auto-send low-risk, high-confidence clarification requests with an audit log,
   keeping a human in the loop only for anything escalated.
4. **Dense embeddings for retrieval**, once running on infra with more headroom than a free
   hosting tier — see the upgrade path documented in `docs/RAG_EXPLAINER.md`.
