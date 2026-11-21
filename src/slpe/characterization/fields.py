"""Characterize the 26 OpenAlex fields via aggregate queries (no bulk downloads).

For each field we measure, over the configured year range, indicators that bear on
*data quality and feasibility* for the link-prediction + disruption pipeline:

    * publication volume and its distribution by year;
    * share of works with an English abstract (``language:en, has_abstract:true``);
    * share (of those) exposing outgoing references (``has_references:true``) — a
      prerequisite for the citation network and the disruption index;
    * subject diversity, proxied by the number of distinct subfields present.

All numbers come from ``meta.count`` and ``group_by`` aggregations, so the whole
26-field sweep costs ~5 cheap requests per field. These are *measured* coverage
indicators, not estimates; every row carries its denominators.

This supports the Stage-1 selection, which must be made on data quality BEFORE any
predictive evaluation (project requirement). Model accuracy is never used here.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field as dc_field
from typing import TYPE_CHECKING, Any

from slpe.config import CharacterizationConfig, TemporalConfig
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


@dataclass(frozen=True)
class FieldYearCounts:
    year: int
    total: int          # works whose primary topic is in this field
    en_abstract: int    # subset: English + reconstructable abstract flagged present
    eligible: int       # subset of en_abstract that also exposes references


@dataclass
class FieldCharacterization:
    field_id: int
    display_name: str
    domain: str
    works_count_all_time: int
    years: list[FieldYearCounts]
    subfield_diversity: int
    # aggregates over [year_min, year_max]
    total_in_range: int
    en_abstract_in_range: int
    eligible_in_range: int
    english_abstract_fraction: float
    with_references_fraction: float
    # eligible volume within each temporal cut's history window [history_start, cut]
    eligible_per_cut: dict[str, int] = dc_field(default_factory=dict)

    @property
    def min_eligible_per_cut(self) -> int:
        return min(self.eligible_per_cut.values()) if self.eligible_per_cut else 0

    def flat_record(self) -> dict[str, Any]:
        """One flat dict per field for tabular export (years collapsed to aggregates)."""
        rec = {k: v for k, v in asdict(self).items() if k != "years"}
        rec["min_eligible_per_cut"] = self.min_eligible_per_cut
        for cut_name, n in self.eligible_per_cut.items():
            rec[f"eligible__{cut_name}"] = n
        rec.pop("eligible_per_cut", None)
        return rec


def _primary_filter(field_id: int, year_min: int, year_max: int, extra: str = "") -> str:
    base = (
        f"primary_topic.field.id:{field_id},"
        f"from_publication_date:{year_min}-01-01,"
        f"to_publication_date:{year_max}-12-31"
    )
    return f"{base},{extra}" if extra else base


def _year_buckets(client: OpenAlexClient, filters: str) -> dict[int, int]:
    """group_by publication_year -> {year: count}, ignoring the 'unknown' bucket."""
    out: dict[int, int] = {}
    for g in client.group_by("works", group_by="publication_year", filters=filters):
        key = g.get("key")
        try:
            year = int(key)
        except (TypeError, ValueError):
            continue
        out[year] = int(g.get("count", 0))
    return out


def characterize_field(
    client: OpenAlexClient,
    field_obj: dict[str, Any],
    ch_cfg: CharacterizationConfig,
    temporal: TemporalConfig,
) -> FieldCharacterization:
    """Characterize one field from its OpenAlex field object + aggregate queries."""
    fid = _field_numeric_id(field_obj["id"])
    name = field_obj.get("display_name", str(fid))
    domain = (field_obj.get("domain") or {}).get("display_name", "unknown")
    works_all_time = int(field_obj.get("works_count", 0))

    ymin, ymax = ch_cfg.year_min, ch_cfg.year_max

    # Three group_by sweeps cover every year at once.
    totals = _year_buckets(client, _primary_filter(fid, ymin, ymax))
    en_abs = _year_buckets(
        client, _primary_filter(fid, ymin, ymax, "has_abstract:true,language:en")
    )
    eligible = _year_buckets(
        client,
        _primary_filter(fid, ymin, ymax, "has_abstract:true,language:en,has_references:true"),
    )

    years = [
        FieldYearCounts(
            year=y,
            total=totals.get(y, 0),
            en_abstract=en_abs.get(y, 0),
            eligible=eligible.get(y, 0),
        )
        for y in range(ymin, ymax + 1)
    ]

    total_in_range = sum(totals.values())
    en_abs_in_range = sum(en_abs.values())
    eligible_in_range = sum(eligible.values())

    english_fraction = (en_abs_in_range / total_in_range) if total_in_range else 0.0
    with_refs_fraction = (eligible_in_range / en_abs_in_range) if en_abs_in_range else 0.0

    # Subject diversity: distinct subfields actually present in the window.
    subfield_buckets = client.group_by(
        "works",
        group_by="primary_topic.subfield.id",
        filters=_primary_filter(fid, ymin, ymax),
    )
    subfield_diversity = sum(
        1 for g in subfield_buckets if g.get("key") not in (None, "unknown") and int(g.get("count", 0)) > 0
    )

    # Eligible volume inside each temporal cut's history window (derived from
    # per-year eligible counts; no extra requests).
    eligible_per_cut: dict[str, int] = {}
    for cut in temporal.cuts:
        eligible_per_cut[cut.name] = sum(
            eligible.get(y, 0) for y in range(cut.history_start, cut.cut + 1)
        )

    return FieldCharacterization(
        field_id=fid,
        display_name=name,
        domain=domain,
        works_count_all_time=works_all_time,
        years=years,
        subfield_diversity=subfield_diversity,
        total_in_range=total_in_range,
        en_abstract_in_range=en_abs_in_range,
        eligible_in_range=eligible_in_range,
        english_abstract_fraction=english_fraction,
        with_references_fraction=with_refs_fraction,
        eligible_per_cut=eligible_per_cut,
    )


def characterize_all_fields(
    client: OpenAlexClient,
    ch_cfg: CharacterizationConfig,
    temporal: TemporalConfig,
    *,
    progress: bool = True,
) -> list[FieldCharacterization]:
    """Characterize all 26 OpenAlex fields. Returns one record per field."""
    fields = client.list_all("fields", per_page=200, select="id,display_name,works_count,domain")
    if len(fields) != 26:
        logger.warning("expected 26 fields, got %d", len(fields))

    results: list[FieldCharacterization] = []
    iterator: Any = fields
    if progress:
        try:
            from tqdm import tqdm

            iterator = tqdm(fields, desc="characterizing fields")
        except ImportError:
            pass

    for fobj in iterator:
        rec = characterize_field(client, fobj, ch_cfg, temporal)
        logger.info(
            "field %s (%s): total=%d en_abs=%.2f refs=%.2f subfields=%d",
            rec.field_id, rec.display_name, rec.total_in_range,
            rec.english_abstract_fraction, rec.with_references_fraction, rec.subfield_diversity,
        )
        results.append(rec)

    results.sort(key=lambda r: r.total_in_range, reverse=True)
    return results


def characterizations_to_dataframe(records: list[FieldCharacterization]) -> "pd.DataFrame":
    """Collapse records into a tidy one-row-per-field DataFrame."""
    import pandas as pd

    return pd.DataFrame([r.flat_record() for r in records])
