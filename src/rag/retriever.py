"""RAG retrieval (PRD-adjacent capability, added on top of the v1.0 classifier).

Filters the indexed knowledge-base chunks to what's actually eligible for a given record
(that vendor's contract, plus the always-eligible policy manual and precedent log), then
ranks by TF-IDF cosine similarity against the query. Returns nothing rather than a weak
match when there's no real hit -- a citation should never be fabricated just to fill a slot.

The index is built once per process via `_load_index()`'s `lru_cache` and kept purely
in-memory (see ingest.py's module docstring for why there's no on-disk/pickled index file).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from sklearn.metrics.pairwise import cosine_similarity

from src.rag.ingest import Chunk, build_index

ALWAYS_ELIGIBLE_DOC_TYPES = {"policy", "precedent"}
DEFAULT_MIN_SCORE = 0.12


@dataclass
class RetrievedChunk:
    text: str
    heading: str
    source_file: str
    doc_type: str
    score: float


@lru_cache(maxsize=1)
def _load_index():
    return build_index()


def reload_index() -> None:
    """Forces a rebuild of the in-memory index -- used by tests / after knowledge_base/ edits."""
    _load_index.cache_clear()
    _load_index()


def retrieve(
    vendor_id: str | None, query_text: str, k: int = 3, min_score: float = DEFAULT_MIN_SCORE
) -> list[RetrievedChunk]:
    index = _load_index()
    chunks: list[Chunk] = index["chunks"]
    vectorizer = index["vectorizer"]
    matrix = index["matrix"]

    eligible_idx = [
        i
        for i, c in enumerate(chunks)
        if c.doc_type in ALWAYS_ELIGIBLE_DOC_TYPES or (vendor_id and c.vendor_id == vendor_id)
    ]
    if not eligible_idx:
        return []

    query_vec = vectorizer.transform([query_text])
    scores = cosine_similarity(query_vec, matrix[eligible_idx])[0]

    ranked = sorted(zip(eligible_idx, scores), key=lambda pair: pair[1], reverse=True)
    results = []
    for idx, score in ranked[:k]:
        if score < min_score:
            continue
        c = chunks[idx]
        results.append(
            RetrievedChunk(text=c.text, heading=c.heading, source_file=c.source_file, doc_type=c.doc_type, score=float(score))
        )
    return results


def build_query(exception_type_label: str, record) -> str:
    """Builds a retrieval query from the exception type + the record's most relevant fields.
    Kept separate from llm_client's prompt-building so the query (used only for similarity
    search) stays simple text, not the full untrusted-data prompt block.
    """
    parts = [exception_type_label]
    if record.payment_terms_invoice or record.payment_terms_contract:
        parts.append(f"invoice terms {record.payment_terms_invoice} contract terms {record.payment_terms_contract}")
    if record.po_amount and record.invoice_amount:
        parts.append(f"PO amount {record.po_amount} invoice amount {record.invoice_amount}")
    if record.qty_ordered is not None and record.qty_received is not None:
        parts.append(f"quantity ordered {record.qty_ordered} quantity received {record.qty_received}")
    return ". ".join(parts)
