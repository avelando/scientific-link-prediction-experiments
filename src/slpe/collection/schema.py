"""Normalize OpenAlex works into typed, relational records for parquet.

Three flat tables (parquet-friendly, no nested structs):
    * publications      — one row per work (metadata + reconstructed abstract).
    * topics            — one row per (work, topic) with score + is_primary.
    * references        — one row per (citing, cited) edge (directed citing->cited).

Design decisions (project §4.1, §4.4):
    * The reconstructed abstract is kept as-is (no destructive normalization here).
    * ``referenced_works`` is preserved as edges; CURRENT cumulative citation counts
      are NOT stored as if they were historical features.
    * OpenAlex topics are kept for delimitation/weighting ONLY; they are not used as
      concepts/vertices (that is a later stage).
    * ``collected_utc`` records provenance per row; it is the retrieval time, not a
      historical snapshot of the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pyarrow as pa

from slpe.openalex.abstracts import reconstruct_with_diagnostics

_ID_TAIL = re.compile(r"[^/]+$")


def short_id(openalex_id: str | None) -> str | None:
    """OpenAlex short id, e.g. 'W123' from a full URL or id."""
    if not openalex_id:
        return None
    m = _ID_TAIL.search(str(openalex_id))
    return m.group(0) if m else None


def _field_id(topic: dict[str, Any] | None, key: str) -> int | None:
    if not topic:
        return None
    node = topic.get(key)
    if not isinstance(node, dict):
        return None
    raw = node.get("id")
    if raw is None:
        return None
    tail = str(raw).rstrip("/").split("/")[-1]
    return int(tail) if tail.isdigit() else None


# --- pyarrow schemas (explicit types, documented meaning) ------------------

PUBLICATIONS_SCHEMA = pa.schema([
    ("work_id", pa.string()),            # OpenAlex short id (W...)
    ("doi", pa.string()),                 # normalized DOI (lowercase, no prefix), or null
    ("title", pa.string()),
    ("abstract", pa.string()),            # reconstructed text, or null if absent
    ("abstract_tokens", pa.int32()),      # token count of the reconstructed abstract
    ("abstract_collisions", pa.int32()),  # integrity diagnostic
    ("publication_year", pa.int32()),
    ("publication_date", pa.string()),
    ("type", pa.string()),
    ("language", pa.string()),
    ("primary_field_id", pa.int32()),
    ("referenced_works_count", pa.int32()),
    ("n_references_present", pa.int32()),  # actual ids present in referenced_works
    ("collected_utc", pa.string()),        # provenance: retrieval time
])

TOPICS_SCHEMA = pa.schema([
    ("work_id", pa.string()),
    ("topic_id", pa.string()),
    ("field_id", pa.int32()),
    ("subfield_id", pa.int32()),
    ("score", pa.float64()),
    ("is_primary", pa.bool_()),
])

REFERENCES_SCHEMA = pa.schema([
    ("citing_id", pa.string()),  # edge orientation: citing -> cited
    ("cited_id", pa.string()),
])


@dataclass
class NormalizedWork:
    publication: dict[str, Any]
    topics: list[dict[str, Any]]
    references: list[dict[str, Any]]


def _normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = str(doi).strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        d = d.removeprefix(prefix)
    return d or None


def normalize_work(work: dict[str, Any], *, collected_utc: str | None = None) -> NormalizedWork:
    """Convert one OpenAlex work dict into relational records."""
    collected_utc = collected_utc or datetime.now(timezone.utc).isoformat()
    wid = short_id(work.get("id"))

    inv = work.get("abstract_inverted_index")
    abstract, diag = reconstruct_with_diagnostics(inv)
    tokens = len(abstract.split()) if abstract else 0

    refs = [short_id(r) for r in (work.get("referenced_works") or []) if r]
    refs = [r for r in refs if r]

    pub = {
        "work_id": wid,
        "doi": _normalize_doi(work.get("doi")),
        "title": work.get("title"),
        "abstract": abstract,
        "abstract_tokens": tokens,
        "abstract_collisions": diag.n_position_collisions,
        "publication_year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "type": work.get("type"),
        "language": work.get("language"),
        "primary_field_id": _field_id(work.get("primary_topic"), "field"),
        "referenced_works_count": work.get("referenced_works_count"),
        "n_references_present": len(refs),
        "collected_utc": collected_utc,
    }

    topic_rows: list[dict[str, Any]] = []
    primary_tid = short_id((work.get("primary_topic") or {}).get("id"))
    for t in work.get("topics") or []:
        if not isinstance(t, dict):
            continue
        tid = short_id(t.get("id"))
        topic_rows.append({
            "work_id": wid,
            "topic_id": tid,
            "field_id": _field_id(t, "field"),
            "subfield_id": _field_id(t, "subfield"),
            "score": float(t["score"]) if isinstance(t.get("score"), (int, float)) else None,
            "is_primary": tid is not None and tid == primary_tid,
        })

    ref_rows = [{"citing_id": wid, "cited_id": r} for r in refs]

    return NormalizedWork(publication=pub, topics=topic_rows, references=ref_rows)
