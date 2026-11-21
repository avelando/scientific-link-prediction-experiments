"""Characterize the 26 OpenAlex fields via aggregate queries (no bulk downloads).

For each field we measure, over the configured year range and for a configurable
set of document ``type`` values, indicators that bear on data quality and
feasibility — separated into three explicit coverage levels so they are never
conflated (addressing the audit):

    1. SEMANTIC corpus    — works of the corpus types with an English abstract
                            (metadata flag). Basis for concept extraction and the
                            semantic network. Does NOT require references.
    2. BIBLIOMETRIC corpus — the semantic subset that also exposes outgoing
                            references (``has_references``). Basis for the citation
                            network. "Reference metadata present" only; it does
                            NOT establish that the disruption index is measurable.
    3. DI-candidate note   — disruption measurability needs citing/cited links and
                            a complete horizon; this phase does NOT claim it here.

Thematic breadth is summarised by the number of subfields present AND a normalized
subfield entropy; subfield COUNT is descriptive only and is never an eliminatory
gate. All numbers come from ``meta.count`` / ``group_by`` aggregations (~5 cheap
requests per field). English-abstract figures are OpenAlex METADATA flags, not a
guarantee of reconstructable text — see ``quality_sampling`` for that.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from typing import TYPE_CHECKING, Any

from slpe.config import CharacterizationConfig, CorpusConfig, TemporalConfig
from slpe.openalex.client import OpenAlexClient

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger("slpe.characterization")

_ID_RE = re.compile(r"(\d+)\s*$")


def _field_numeric_id(raw_id: str) -> int:
    """Extract the bare numeric field id from an OpenAlex field id/URL."""
    m = _ID_RE.search(str(raw_id))
    if not m:
        raise ValueError(f"cannot parse field id from {raw_id!r}")
    return int(m.group(1))


def normalized_entropy(counts: list[int]) -> float:
    """Shannon entropy of a distribution, normalized to [0, 1] by log(k).

    Returns 0.0 for 0 or 1 non-empty categories. A value near 1 means works are
    spread evenly across subfields; near 0 means concentration in a few.
    """
    positive = [c for c in counts if c > 0]
    k = len(positive)
    if k <= 1:
        return 0.0
    total = sum(positive)
    h = -sum((c / total) * math.log(c / total) for c in positive)
    return h / math.log(k)


@dataclass(frozen=True)
class FieldYearCounts:
    year: int
    all_types: int      # works of ANY type (denominator for type coverage)
    corpus_type: int     # works of the configured corpus types
    semantic: int        # corpus_type + English + abstract flag
    bibliometric: int    # semantic + has_references


@dataclass
class FieldCharacterization:
    field_id: int
    display_name: str
    domain: str
    works_count_all_time: int
    corpus_types: tuple[str, ...]
    years: list[FieldYearCounts]
    subfield_count: int           # descriptive only (NOT a gate)
    subfield_entropy: float       # normalized thematic breadth, descriptive
    # aggregates over [year_min, year_max]
    all_types_in_range: int
    corpus_type_in_range: int
    semantic_in_range: int
    bibliometric_in_range: int
    type_fraction: float              # corpus_type / all_types
    english_abstract_fraction: float  # semantic / corpus_type (METADATA proxy)
    with_references_fraction: float   # bibliometric / semantic
    # per-cut volumes within each cut's history window [history_start, cut]
    semantic_eligible_per_cut: dict[str, int] = dc_field(default_factory=dict)
    bibliometric_eligible_per_cut: dict[str, int] = dc_field(default_factory=dict)

    @property
    def min_semantic_eligible_per_cut(self) -> int:
        v = self.semantic_eligible_per_cut
        return min(v.values()) if v else 0

    @property
    def min_bibliometric_eligible_per_cut(self) -> int:
        v = self.bibliometric_eligible_per_cut
        return min(v.values()) if v else 0

    def flat_record(self) -> dict[str, Any]:
        rec = {k: v for k, v in asdict(self).items() if k not in ("years",)}
        rec["corpus_types"] = ",".join(self.corpus_types)
        rec["min_semantic_eligible_per_cut"] = self.min_semantic_eligible_per_cut
        rec["min_bibliometric_eligible_per_cut"] = self.min_bibliometric_eligible_per_cut
        for cut_name, n in self.semantic_eligible_per_cut.items():
            rec[f"semantic__{cut_name}"] = n
        for cut_name, n in self.bibliometric_eligible_per_cut.items():
            rec[f"biblio__{cut_name}"] = n
        rec.pop("semantic_eligible_per_cut", None)
        rec.pop("bibliometric_eligible_per_cut", None)
        return rec


def _base_filter(field_id: int, year_min: int, year_max: int, extra: str = "") -> str:
    base = (
        f"primary_topic.field.id:{field_id},"
        f"from_publication_date:{year_min}-01-01,"
        f"to_publication_date:{year_max}-12-31"
    )
    return f"{base},{extra}" if extra else base


def _year_buckets(client: OpenAlexClient, filters: str) -> dict[int, int]:
    out: dict[int, int] = {}
    for g in client.group_by("works", group_by="publication_year", filters=filters):
        try:
            year = int(g.get("key"))
        except (TypeError, ValueError):
            continue
        out[year] = int(g.get("count", 0))
    return out


def characterize_field(
    client: OpenAlexClient,
    field_obj: dict[str, Any],
    ch_cfg: CharacterizationConfig,
    temporal: TemporalConfig,
    corpus: CorpusConfig,
) -> FieldCharacterization:
    """Characterize one field from its OpenAlex field object + aggregate queries."""
    fid = _field_numeric_id(field_obj["id"])
    name = field_obj.get("display_name", str(fid))
    domain = (field_obj.get("domain") or {}).get("display_name", "unknown")
    works_all_time = int(field_obj.get("works_count", 0))
    ymin, ymax = ch_cfg.year_min, ch_cfg.year_max

    type_filter = f"type:{CorpusConfig.types_filter(corpus.types)}"
    en_abs = "has_abstract:true,language:en" if corpus.require_english_abstract else "has_abstract:true"

    all_types = _year_buckets(client, _base_filter(fid, ymin, ymax))
    corpus_type = _year_buckets(client, _base_filter(fid, ymin, ymax, type_filter))
    semantic = _year_buckets(client, _base_filter(fid, ymin, ymax, f"{type_filter},{en_abs}"))
    bibliometric = _year_buckets(
        client, _base_filter(fid, ymin, ymax, f"{type_filter},{en_abs},has_references:true")
    )

    years = [
        FieldYearCounts(
            year=y,
            all_types=all_types.get(y, 0),
            corpus_type=corpus_type.get(y, 0),
            semantic=semantic.get(y, 0),
            bibliometric=bibliometric.get(y, 0),
        )
        for y in range(ymin, ymax + 1)
    ]

    all_in_range = sum(all_types.values())
    type_in_range = sum(corpus_type.values())
    sem_in_range = sum(semantic.values())
    bib_in_range = sum(bibliometric.values())

    type_fraction = (type_in_range / all_in_range) if all_in_range else 0.0
    english_fraction = (sem_in_range / type_in_range) if type_in_range else 0.0
    with_refs_fraction = (bib_in_range / sem_in_range) if sem_in_range else 0.0

    # Subject breadth: distinct subfields present + normalized entropy of the
    # subfield distribution (over the corpus-type works, so it reflects the corpus).
    subfield_buckets = client.group_by(
        "works", group_by="primary_topic.subfield.id",
        filters=_base_filter(fid, ymin, ymax, type_filter),
    )
    subfield_counts = [
        int(g.get("count", 0)) for g in subfield_buckets
        if g.get("key") not in (None, "unknown")
    ]
    subfield_count = sum(1 for c in subfield_counts if c > 0)
    subfield_entropy = normalized_entropy(subfield_counts)

    semantic_per_cut: dict[str, int] = {}
    biblio_per_cut: dict[str, int] = {}
    for cut in temporal.cuts:
        yrs = range(cut.history_start, cut.cut + 1)
        semantic_per_cut[cut.name] = sum(semantic.get(y, 0) for y in yrs)
        biblio_per_cut[cut.name] = sum(bibliometric.get(y, 0) for y in yrs)

    return FieldCharacterization(
        field_id=fid,
        display_name=name,
        domain=domain,
        works_count_all_time=works_all_time,
        corpus_types=tuple(corpus.types),
        years=years,
        subfield_count=subfield_count,
        subfield_entropy=subfield_entropy,
        all_types_in_range=all_in_range,
        corpus_type_in_range=type_in_range,
        semantic_in_range=sem_in_range,
        bibliometric_in_range=bib_in_range,
        type_fraction=type_fraction,
        english_abstract_fraction=english_fraction,
        with_references_fraction=with_refs_fraction,
        semantic_eligible_per_cut=semantic_per_cut,
        bibliometric_eligible_per_cut=biblio_per_cut,
    )


def characterize_all_fields(
    client: OpenAlexClient,
    ch_cfg: CharacterizationConfig,
    temporal: TemporalConfig,
    corpus: CorpusConfig,
    *,
    limit: int | None = None,
    progress: bool = True,
) -> list[FieldCharacterization]:
    """Characterize the OpenAlex fields. ``limit`` restricts the number of fields
    processed BEFORE any queries are issued (cheap smoke tests)."""
    fields = client.list_all("fields", per_page=200, select="id,display_name,works_count,domain")
    if len(fields) != 26:
        logger.warning("expected 26 fields, got %d", len(fields))
    if limit is not None:
        fields = fields[:limit]

    results: list[FieldCharacterization] = []
    iterator: Any = fields
    if progress:
        try:
            from tqdm import tqdm

            iterator = tqdm(fields, desc="characterizing fields")
        except ImportError:
            pass

    for fobj in iterator:
        rec = characterize_field(client, fobj, ch_cfg, temporal, corpus)
        logger.info(
            "field %s (%s): type_total=%d semantic=%.2f refs=%.2f subfields=%d H=%.2f",
            rec.field_id, rec.display_name, rec.corpus_type_in_range,
            rec.english_abstract_fraction, rec.with_references_fraction,
            rec.subfield_count, rec.subfield_entropy,
        )
        results.append(rec)

    results.sort(key=lambda r: r.min_semantic_eligible_per_cut, reverse=True)
    return results


def characterizations_to_dataframe(records: list[FieldCharacterization]) -> pd.DataFrame:
    import pandas as pd

    return pd.DataFrame([r.flat_record() for r in records])


def years_to_dataframe(records: list[FieldCharacterization]) -> pd.DataFrame:
    """Long-form per-field, per-year counts for the yearly figures."""
    import pandas as pd

    rows = []
    for r in records:
        for y in r.years:
            rows.append({
                "field_id": r.field_id,
                "display_name": r.display_name,
                "year": y.year,
                "all_types": y.all_types,
                "corpus_type": y.corpus_type,
                "semantic": y.semantic,
                "bibliometric": y.bibliometric,
            })
    return pd.DataFrame(rows)
