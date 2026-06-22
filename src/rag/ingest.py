"""RAG knowledge-base ingestion.

Reads every Markdown doc in `knowledge_base/` (vendor contracts, the AP policy manual, and
the resolved-exceptions precedent log), splits each into heading-level chunks, and fits a
TF-IDF vectorizer over the corpus. Returns the index as an in-memory object -- it is NOT
persisted to disk.

Two deliberate tradeoffs here, both documented in docs/RAG_EXPLAINER.md:

1. TF-IDF instead of dense/transformer embeddings: the deployed free-tier instance has
   limited RAM, and TF-IDF + scikit-learn (already a project dependency) keeps the footprint
   small. This is a lexical rather than semantic similarity measure -- a deliberate tradeoff,
   not an oversight.
2. No on-disk persistence (no pickle/joblib file): the knowledge base is small (a few dozen
   markdown files), so refitting TF-IDF at process start costs milliseconds -- there's no
   real need for a serialized index artifact. This also sidesteps deserialization risk
   entirely (no pickle.load of anything, ever) rather than relying on "this pickle file is
   only ever written by our own ingest step" as a safety argument.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sklearn.feature_extraction.text import TfidfVectorizer

ROOT = Path(__file__).resolve().parent.parent.parent
KNOWLEDGE_BASE_DIR = ROOT / "knowledge_base"

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)", re.DOTALL)
_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


@dataclass
class Chunk:
    text: str
    heading: str
    source_file: str
    doc_type: str  # "contract" | "policy" | "precedent"
    vendor_id: str | None = None
    vendor_name: str | None = None
    metadata: dict = field(default_factory=dict)


def _parse_doc(path: Path) -> tuple[dict, str]:
    raw = path.read_text()
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return {}, raw
    frontmatter_text, body = match.groups()
    metadata = yaml.safe_load(frontmatter_text) or {}
    return metadata, body


def _chunk_body(body: str) -> list[tuple[str, str]]:
    """Splits a doc body into (heading, text) pairs at each '## ' heading. Content before
    the first heading (e.g. the H1 title line) is dropped -- it carries no retrievable
    content of its own.
    """
    parts = _HEADING_RE.split(body)
    # re.split with a capturing group interleaves: [pre-text, heading1, text1, heading2, text2, ...]
    chunks = []
    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        text = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if text:
            chunks.append((heading, text))
    return chunks


def _doc_type_for(path: Path) -> str:
    if "vendor_contracts" in path.parts:
        return "contract"
    if "policies" in path.parts:
        return "policy"
    if "precedents" in path.parts:
        return "precedent"
    return "other"


def load_chunks() -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(KNOWLEDGE_BASE_DIR.rglob("*.md")):
        metadata, body = _parse_doc(path)
        doc_type = metadata.get("doc_type") or _doc_type_for(path)
        vendor_id = metadata.get("vendor_id")
        vendor_name = metadata.get("vendor_name")
        rel_path = str(path.relative_to(ROOT))
        for heading, text in _chunk_body(body):
            chunks.append(
                Chunk(
                    text=text,
                    heading=heading,
                    source_file=rel_path,
                    doc_type=doc_type,
                    vendor_id=vendor_id,
                    vendor_name=vendor_name,
                    metadata=metadata,
                )
            )
    return chunks


def build_index() -> dict:
    """Returns {"chunks": [...], "vectorizer": ..., "matrix": ...} entirely in-memory."""
    chunks = load_chunks()
    if not chunks:
        raise RuntimeError(f"No knowledge base documents found under {KNOWLEDGE_BASE_DIR}")

    corpus = [f"{c.heading}. {c.text}" for c in chunks]
    vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
    matrix = vectorizer.fit_transform(corpus)
    return {"chunks": chunks, "vectorizer": vectorizer, "matrix": matrix}


def main() -> None:
    """Validates the knowledge base builds cleanly -- used as a fail-fast boot check (see
    render.yaml's start command) and for local debugging. Builds in-memory only; nothing is
    written to disk.
    """
    index = build_index()
    chunks = index["chunks"]
    by_type: dict[str, int] = {}
    for c in chunks:
        by_type[c.doc_type] = by_type.get(c.doc_type, 0) + 1
    print(f"Indexed {len(chunks)} chunks from {KNOWLEDGE_BASE_DIR}")
    print("By doc type:", by_type)
    print("Vendor contracts covered:", sorted({c.vendor_id for c in chunks if c.vendor_id}))


if __name__ == "__main__":
    main()
