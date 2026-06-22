# How RAG Works in the PO Exception Triage Agent

## The problem it solves

Without retrieval, the classifier's only input is one structured CSV row — PO Number,
amounts, dates, a flat `Payment Terms` string. That's everything the model gets to reason
with. If a vendor's actual contract has a clause like *"Net 30 standard, but Net 45 applies
automatically to Q4 orders per Addendum B,"* none of that nuance exists anywhere in the
structured data. The row just looks like a Terms Conflict the model has to guess about.

RAG (Retrieval-Augmented Generation) adds a lookup step before the model answers: search a
knowledge base of real documents, pull back the passages relevant to *this specific record*,
and hand those to the model alongside the structured data. The model's classification — and
its written rationale — is now grounded in an actual source it can cite, not just an
inference from eight fields.

## Why this matters specifically for supply chain / procurement

1. **Contracts are long and vendor-specific.** A flat `payment_terms_contract` column can't
   capture "except during peak season" or "unless the PO exceeds $1.5M." RAG retrieves that
   specific vendor's actual clause instead of assuming the standard term always applies.
2. **Institutional knowledge lives in policy manuals, not transaction data.** "When do we
   auto-approve a price variance under $10K vs. escalate it?" is written down somewhere (an
   AP policy doc), not encoded in any PO/invoice field. RAG retrieves the actual policy text
   and reasons from it.
3. **Precedent matters for consistency.** If a vendor had a similar duplicate-invoice issue
   resolved a certain way three months ago, a procurement manager expects today's decision to
   be consistent with that precedent — not re-litigated from scratch.
4. **Auditability.** This is the one that matters most for a finance/procurement audience.
   Compare:
   - *Without RAG:* "Financial exposure and severity are high enough to require manager
     sign-off." — generic, not verifiable.
   - *With RAG:* "Approved — Net 60 is contractually valid for Q4 orders per Meadows PLC's
     Addendum B, signed 2025-09-12." — a citation a human reviewer can go check. That's the
     difference between an AI agent finance teams trust and one they keep double-checking.

## How it's built here

```
knowledge_base/
├── vendor_contracts/V-XXXX_<slug>.md   one file per vendor with a contract on file
├── policies/ap_policy_manual.md        always-eligible internal AP policy
└── precedents/resolved_exceptions_log.md  always-eligible past-case log
```

**Ingestion (`src/rag/ingest.py`)** reads every Markdown file, splits each into chunks at
`##` headings, extracts metadata (vendor_id, doc_type) from a YAML frontmatter block, and
fits a `TfidfVectorizer` over the whole corpus.

**Retrieval (`src/rag/retriever.py`)** runs in two stages, which matters more than the exact
similarity metric used:
1. **Metadata filter first** — narrow the candidate set to *this record's vendor's* contract
   chunks, plus the policy manual and precedent log (always eligible regardless of vendor).
   This is what stops the system from retrieving an irrelevant vendor's clause just because
   the wording happens to be similar.
2. **Similarity ranking second** — within that filtered set, rank by cosine similarity
   against a query built from the exception type and the record's key fields, return the
   top-k above a minimum score (returns nothing rather than a weak, misleading match when
   there's no real hit).

**Integration (`src/classifier.py` → `src/llm_client.py`)** — for ambiguous rows that already
route to Claude for disambiguation (PRD 3.2's hybrid design), retrieved passages are injected
as their own `<retrieved_context>` block, explicitly labeled as trusted internal knowledge and
kept separate from the `<untrusted_record>` block that holds the vendor-supplied PO/invoice
data. That separation isn't cosmetic — it's the same prompt-injection mitigation from the
project's `/cso` security audit, extended to a second data source.

## A worked example

**PO-000071, Vendor Meadows PLC (V-0171).** The rule engine flags two candidate exceptions —
Price Variance and Missing Fields — for this record, so it's ambiguous and gets routed to the
LLM. Before that call, retrieval runs against Meadows PLC's contract:

```
[0.634] Payment Terms: "Standard payment terms are Net 45 from invoice date..."
[0.365] Escalation Notes: "Any payment-terms discrepancy outside the Q4 window
        should still be treated as a genuine Terms Conflict..."
[0.267] Seasonal Volume Addendum (Addendum B): "...for any PO issued between
        October 1 and December 31, payment terms automatically extend to Net 60..."
```

These three passages go into the prompt's `<retrieved_context>` block. If the invoice in
question is dated in Q4 and shows Net 60 against a PO that lists Net 45, the model can now
correctly recognize this as the contractually-authorized seasonal addendum rather than a
genuine conflict — and cite `knowledge_base/vendor_contracts/V-0171_meadows-plc.md` in its
rationale.

## Security: citations are verified, never trusted blindly

The model is asked to return a `citations` field listing which retrieved sources it actually
used. That list is **never trusted as-is** — `src/classifier.py` cross-checks every claimed
citation against the `source_file` values that were genuinely retrieved and shown to the
model for that record, and silently drops anything that doesn't match. This closes the
obvious failure mode: a prompt-injection attempt (or a hallucination) claiming a citation to
a document the model was never shown, which would otherwise look like a verified, audit-ready
source when it's fabricated. Verified in `test`-style scripts during development by forging a
fake citation and confirming it gets filtered to an empty list.

## Deliberate engineering tradeoffs (and the upgrade path)

**TF-IDF instead of dense/transformer embeddings.** A "real" RAG system usually uses a neural
embedding model (e.g. `sentence-transformers`) plus a vector database (e.g. Chroma, FAISS,
pgvector). This project deliberately uses TF-IDF + cosine similarity (via scikit-learn,
already a dependency) instead, for one concrete reason: the public deployment runs on
Render's free tier (~512MB RAM), and `sentence-transformers` pulls in PyTorch, which alone
can exceed that budget once Streamlit and the rest of the app are also loaded. TF-IDF is a
classic, legitimate information-retrieval technique — it just measures lexical overlap
(shared vocabulary) rather than semantic meaning, so it works well here because contract
language is fairly distinctive and the vendor-filter step does most of the precision work
before similarity ranking even runs.

**No persisted index file.** The knowledge base is small enough (a few dozen files) that
rebuilding the TF-IDF index from scratch at process start costs milliseconds. There's
genuinely no need for a serialized on-disk artifact, which also means there's no
deserialization step to worry about at all — a smaller, more defensible design than "this
file is safe because only our own code writes it."

**Upgrade path for bigger infra.** Anyone running this locally or on a larger instance can
swap `TfidfVectorizer` for a `sentence-transformers` embedding model and the cosine-similarity
scan for a real vector index (Chroma/FAISS) without changing the retrieval *interface*
(`retrieve(vendor_id, query_text, k)` stays the same) — only `ingest.py`'s vectorization step
and `retriever.py`'s similarity computation would need to change. Semantic embeddings would
catch paraphrased matches TF-IDF misses (e.g. "extended payment window" vs. "Net 60 terms"),
at the cost of the RAM/dependency footprint this project specifically avoided for its free-tier
deployment.

## What this doesn't do (yet)

RAG here only grounds the **LLM disambiguation path** — the ambiguous, multi-match rows that
already needed an LLM call. It does not currently feed back into the deterministic rule
engine's classification of unambiguous rows (e.g., automatically overriding a rule-flagged
Price Variance when a matching escalation clause is found, even when the row wasn't otherwise
ambiguous). That's a real, valuable extension — and a deliberately scoped-out one for this
phase, documented as a roadmap item in `docs/CLIENT_ENGAGEMENT.md` rather than built now.
