"""Validate textual quality on reproducible samples of real works.

``english_abstract_fraction`` from the aggregate characterization is a METADATA
flag: it counts works OpenAlex marks as having an abstract in English. It does not
prove the abstract reconstructs into usable text. This module draws a bounded,
reproducible sample of real works per candidate field and inspects each record:
title present, language, abstract reconstructable and its token count, empty/
malformed content, references present, and date consistency.

Coverage estimates are reported with Wilson score confidence intervals so they are
clearly SAMPLE estimates with uncertainty, distinct from the exact aggregate
counts. Sample sizes are chosen from a target margin of error, not arbitrarily.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from slpe.openalex.abstracts import reconstruct_abstract
from slpe.openalex.client import OpenAlexClient

_SELECT = "id,title,abstract_inverted_index,language,referenced_works,publication_year,publication_date,type"


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion k/n."""
    if n == 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def sample_size_for_margin(margin: float = 0.05, z: float = 1.96, p: float = 0.5) -> int:
    """Sample size for a target margin of error at worst-case variance (p=0.5)."""
    return math.ceil((z * z * p * (1 - p)) / (margin * margin))


@dataclass
class WorkInspection:
    has_title: bool
    language_en: bool
    abstract_present_flag: bool      # inverted index present
    abstract_reconstructable: bool   # non-empty text after reconstruction
    abstract_tokens: int
    short_abstract: bool             # < 20 tokens (likely truncated/placeholder)
    has_references: bool
    date_present: bool
    year_consistent: bool            # publication_year matches publication_date year


def inspect_work(work: dict[str, Any], *, min_tokens: int = 20) -> WorkInspection:
    title = work.get("title")
    has_title = bool(isinstance(title, str) and title.strip())
    lang = work.get("language")
    inv = work.get("abstract_inverted_index")
    abstract_present = bool(inv)
    text = reconstruct_abstract(inv) if abstract_present else None
    tokens = len(text.split()) if text else 0
    refs = work.get("referenced_works") or []
    date = work.get("publication_date")
    year = work.get("publication_year")
    year_consistent = bool(date and year and str(date).startswith(str(year)))
    return WorkInspection(
        has_title=has_title,
        language_en=(lang == "en"),
        abstract_present_flag=abstract_present,
        abstract_reconstructable=bool(text),
        abstract_tokens=tokens,
        short_abstract=bool(text) and tokens < min_tokens,
        has_references=len(refs) > 0,
        date_present=bool(date),
        year_consistent=year_consistent,
    )


@dataclass
class QualityReport:
    field_id: int
    n_sampled: int
    corpus_filter: str
    # fractions with Wilson 95% CIs
    frac_title: float
    frac_language_en: float
    frac_abstract_present: float
    frac_abstract_reconstructable: float
    frac_short_abstract: float
    frac_has_references: float
    frac_year_consistent: float
    median_tokens: float
    ci: dict[str, tuple[float, float]]

    def to_flat(self) -> dict[str, Any]:
        d = {k: v for k, v in asdict(self).items() if k != "ci"}
        for name, (lo, hi) in self.ci.items():
            d[f"{name}_ci_lo"] = lo
            d[f"{name}_ci_hi"] = hi
        return d


def summarize_inspections(field_id: int, corpus_filter: str,
                          inspections: list[WorkInspection]) -> QualityReport:
    import statistics

    n = len(inspections)

    def frac(pred) -> tuple[float, int]:
        k = sum(1 for i in inspections if pred(i))
        return (k / n if n else 0.0, k)

    f_title, k_title = frac(lambda i: i.has_title)
    f_en, k_en = frac(lambda i: i.language_en)
    f_absp, k_absp = frac(lambda i: i.abstract_present_flag)
    f_absr, k_absr = frac(lambda i: i.abstract_reconstructable)
    f_short, k_short = frac(lambda i: i.short_abstract)
    f_refs, k_refs = frac(lambda i: i.has_references)
    f_year, k_year = frac(lambda i: i.year_consistent)
    med_tokens = statistics.median([i.abstract_tokens for i in inspections]) if n else 0.0

    ci = {
        "frac_title": wilson_interval(k_title, n),
        "frac_language_en": wilson_interval(k_en, n),
        "frac_abstract_present": wilson_interval(k_absp, n),
        "frac_abstract_reconstructable": wilson_interval(k_absr, n),
        "frac_short_abstract": wilson_interval(k_short, n),
        "frac_has_references": wilson_interval(k_refs, n),
        "frac_year_consistent": wilson_interval(k_year, n),
    }
    return QualityReport(
        field_id=field_id, n_sampled=n, corpus_filter=corpus_filter,
        frac_title=f_title, frac_language_en=f_en, frac_abstract_present=f_absp,
        frac_abstract_reconstructable=f_absr, frac_short_abstract=f_short,
        frac_has_references=f_refs, frac_year_consistent=f_year,
        median_tokens=med_tokens, ci=ci,
    )


def sample_field_quality(
    client: OpenAlexClient,
    field_id: int,
    *,
    corpus_filter: str,
    n: int,
    seed: int = 0,
) -> QualityReport:
    """Draw a reproducible sample and inspect text quality.

    Uses OpenAlex ``sample`` with a fixed seed for reproducibility. Only inspects
    real records (no fabrication); returns coverage with confidence intervals.
    """
    inspections: list[WorkInspection] = []
    # OpenAlex reproducible random sampling via `sample` + `seed`, paged with
    # `page`/`per-page` (sampling is incompatible with cursor paging).
    per_page = min(n, 200)
    n_pages = (n + per_page - 1) // per_page
    for page in range(1, n_pages + 1):
        params = {
            "filter": f"primary_topic.field.id:{field_id},{corpus_filter}",
            "sample": n, "seed": seed, "per-page": per_page, "page": page,
            "select": _SELECT,
        }
        payload = client.get("works", params)
        results = payload.get("results", [])
        for work in results:
            inspections.append(inspect_work(work))
        if len(results) < per_page:
            break
    return summarize_inspections(field_id, corpus_filter, inspections)


def sample_field_quality_by_year(
    client: OpenAlexClient,
    field_id: int,
    *,
    corpus_filter: str,
    years: range,
    n_per_year: int,
    seed: int = 0,
) -> list[QualityReport]:
    """Stratify the quality sample by publication year.

    Checks whether reconstructability / length / reference coverage differ across
    historical periods — important because older records may have sparser metadata.
    Returns one :class:`QualityReport` per year (its ``corpus_filter`` records the
    year so the stratum is reproducible).
    """
    reports: list[QualityReport] = []
    for year in years:
        year_filter = f"{corpus_filter},publication_year:{year}"
        rep = sample_field_quality(client, field_id, corpus_filter=year_filter,
                                   n=n_per_year, seed=seed)
        reports.append(rep)
    return reports
