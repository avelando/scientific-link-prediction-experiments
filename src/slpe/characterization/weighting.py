"""Weighted field attribution — an OpenAlex adaptation of Brito et al. (2023).

Brito, Silva & Amancio (2023) classify a paper into major fields with a weight
``w_P(f_top)`` obtained by walking the Microsoft Academic Graph subfield→field DAG
and splitting each subfield's contribution across its parent fields. OpenAlex
already ships a fixed topic→subfield→field→domain tree and a per-topic ``score``,
so we ADAPT the principle rather than copy the formula:

    * Primary attribution:  the field of ``primary_topic`` (one field per work).
    * Weighted attribution: distribute each work across the fields of its
      ``topics`` in proportion to the topics' scores, normalized to sum to 1 per
      work. Multiple topics in the same field add up; topics in different fields
      split the work — a view of multidisciplinarity the primary view hides.

IMPORTANT: OpenAlex topic ``score`` values are model outputs, NOT calibrated
probabilities. We use them only as relative weights and say so. This module does
the delimitation/characterization of corpora; it does NOT replace the scientific
concept extraction of a later stage.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from slpe.openalex.client import OpenAlexClient


def _field_id_of(topic: dict[str, Any] | None) -> int | None:
    if not topic:
        return None
    fld = topic.get("field")
    if not isinstance(fld, dict):
        return None
    raw = fld.get("id")
    if raw is None:
        return None
    # field id may be a URL or bare int
    s = str(raw).rstrip("/").split("/")[-1]
    return int(s) if s.isdigit() else None


def primary_field(work: dict[str, Any]) -> int | None:
    """Field id of the work's primary topic, or None if unavailable."""
    return _field_id_of(work.get("primary_topic"))


def work_field_weights(work: dict[str, Any]) -> dict[int, float]:
    """Distribute one work across fields by normalized topic scores.

    Rules (defensive against malformed metadata):
        * No usable topics -> empty dict (the work contributes nowhere).
        * Missing/invalid scores -> treated as equal weights among valid topics.
        * Negative scores -> clamped to 0.
        * Weights are normalized to sum to 1 across the work's fields.
    """
    topics = work.get("topics")
    if not isinstance(topics, list) or not topics:
        # Fall back to the primary topic as a single-field unit weight.
        fid = primary_field(work)
        return {fid: 1.0} if fid is not None else {}

    field_scores: dict[int, float] = defaultdict(float)
    any_valid_score = False
    valid_fields: list[int] = []
    for t in topics:
        if not isinstance(t, dict):
            continue
        fid = _field_id_of(t)
        if fid is None:
            continue
        valid_fields.append(fid)
        score = t.get("score")
        if isinstance(score, (int, float)) and score > 0:
            field_scores[fid] += float(score)
            any_valid_score = True

    if not valid_fields:
        fid = primary_field(work)
        return {fid: 1.0} if fid is not None else {}

    if not any_valid_score:
        # Equal split across the distinct valid fields.
        uniq = sorted(set(valid_fields))
        w = 1.0 / len(uniq)
        return {fid: w for fid in uniq}

    total = sum(field_scores.values())
    return {fid: s / total for fid, s in field_scores.items()}


@dataclass
class FieldAttribution:
    primary_counts: dict[int, float]   # whole-work counts by primary field
    weighted_counts: dict[int, float]  # fractional counts by weighted membership
    n_works: int
    n_multidisciplinary: int           # works whose weight spans >1 field

    def primary_share(self, field_id: int) -> float:
        return self.primary_counts.get(field_id, 0.0) / self.n_works if self.n_works else 0.0

    def weighted_share(self, field_id: int) -> float:
        total = sum(self.weighted_counts.values())
        return self.weighted_counts.get(field_id, 0.0) / total if total else 0.0


def aggregate_field_distribution(works: Iterable[dict[str, Any]]) -> FieldAttribution:
    """Compare primary vs weighted field distributions over a set of works."""
    primary: dict[int, float] = defaultdict(float)
    weighted: dict[int, float] = defaultdict(float)
    n = 0
    n_multi = 0
    for w in works:
        n += 1
        pf = primary_field(w)
        if pf is not None:
            primary[pf] += 1.0
        wts = work_field_weights(w)
        if len(wts) > 1:
            n_multi += 1
        for fid, weight in wts.items():
            weighted[fid] += weight
    return FieldAttribution(dict(primary), dict(weighted), n, n_multi)


def sample_works_for_field(
    client: OpenAlexClient,
    field_id: int,
    *,
    corpus_filter: str,
    max_works: int,
) -> list[dict[str, Any]]:
    """Fetch up to ``max_works`` works of a field with their topic metadata.

    Uses cursor pagination with a hard cap. Only the fields needed for attribution
    are selected, to minimise payload. Sampling here is for CHARACTERIZATION of the
    field/topic structure, not for building the predictive corpus.
    """
    filters = f"primary_topic.field.id:{field_id},{corpus_filter}"
    out: list[dict[str, Any]] = []
    for work in client.paginate(
        "works", filters=filters, select="id,primary_topic,topics", per_page=200
    ):
        out.append(work)
        if len(out) >= max_works:
            break
    return out
