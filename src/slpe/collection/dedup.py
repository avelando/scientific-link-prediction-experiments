"""Deduplication and version linking for collected publications.

Rules (project §4.1 — link versions, preserve dates, never back-date content):

    1. same_work_id  (exact)      — identical OpenAlex id: keep one, drop the rest.
    2. same_doi      (confirmed)  — records sharing a normalized DOI are versions of
                                    one work. Canonical = earliest publication_date
                                    (tie-break: has abstract, then work_id). Others
                                    are version-linked and removed from the canonical
                                    set, with their dates preserved in the linkage log.
    3. same_title_year (uncertain)— same normalized title AND year but DIFFERENT DOI:
                                    flagged as POSSIBLE duplicates, NOT merged (distinct
                                    publications can share a title). Both are kept.

Every removal/merge is recorded in a linkage table with its rule and confidence, so
nothing is dropped silently. Titles are normalized only for matching; stored titles
are untouched.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def normalize_title(title: str | None) -> str | None:
    if not title or not isinstance(title, str):
        return None
    t = _PUNCT.sub(" ", title.lower())
    t = _WS.sub(" ", t).strip()
    return t or None


def deduplicate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (canonical_publications, linkage_log).

    ``linkage_log`` columns: work_id, canonical_id, rule, confidence, reason.
    """
    import pandas as pd

    if df.empty:
        return df.copy(), pd.DataFrame(
            columns=["work_id", "canonical_id", "rule", "confidence", "reason"])

    work = df.copy()
    work["_date"] = work["publication_date"].fillna("9999-12-31")
    work["_has_abs"] = work["abstract"].notna()
    links: list[dict] = []

    # 1. Exact duplicate work_id -> keep first.
    dupe_ids = work[work["work_id"].duplicated(keep="first")]
    for wid in dupe_ids["work_id"]:
        links.append({"work_id": wid, "canonical_id": wid, "rule": "same_work_id",
                      "confidence": "confirmed", "reason": "identical OpenAlex id"})
    work = work.drop_duplicates(subset="work_id", keep="first")

    # 2. Version link by DOI (confirmed).
    keep_mask = pd.Series(True, index=work.index)
    doi_groups = work[work["doi"].notna()].groupby("doi")
    for doi, grp in doi_groups:
        if len(grp) < 2:
            continue
        # Canonical: earliest date, then has-abstract, then work_id.
        ordered = grp.sort_values(
            by=["_date", "_has_abs", "work_id"], ascending=[True, False, True])
        canonical = ordered.iloc[0]["work_id"]
        for _, row in ordered.iloc[1:].iterrows():
            links.append({"work_id": row["work_id"], "canonical_id": canonical,
                          "rule": "same_doi", "confidence": "confirmed",
                          "reason": f"shared DOI {doi}; date {row['publication_date']}"})
            keep_mask.loc[row.name] = False
    work = work[keep_mask]

    # 3. Uncertain: same normalized title + year, different DOI -> flag, keep both.
    work["_ntitle"] = work["title"].map(normalize_title)
    cand = work[work["_ntitle"].notna() & work["publication_year"].notna()]
    for (_, _), grp in cand.groupby(["_ntitle", "publication_year"]):
        if len(grp) < 2:
            continue
        dois = set(grp["doi"].dropna())
        if len(dois) > 1 or grp["doi"].isna().any():
            ids = list(grp["work_id"])
            for wid in ids[1:]:
                links.append({"work_id": wid, "canonical_id": ids[0],
                              "rule": "same_title_year", "confidence": "uncertain",
                              "reason": "same title+year, different/missing DOI; NOT merged"})

    canonical_df = work.drop(columns=["_date", "_has_abs", "_ntitle"], errors="ignore")
    linkage_df = pd.DataFrame(
        links, columns=["work_id", "canonical_id", "rule", "confidence", "reason"])
    return canonical_df, linkage_df


def canonical_mapping(linkage_df: pd.DataFrame) -> dict[str, str]:
    """Build an original-id -> canonical-id map from CONFIRMED links only.

    Uncertain matches are NOT remapped (they are flags, not merges). The map lets
    related tables (references, topics) consistently use canonical ids.
    """
    if linkage_df.empty:
        return {}
    confirmed = linkage_df[linkage_df["confidence"] == "confirmed"]
    return dict(zip(confirmed["work_id"], confirmed["canonical_id"]))


def apply_canonical_mapping(
    df: pd.DataFrame, mapping: dict[str, str], columns: list[str]
) -> pd.DataFrame:
    """Remap id columns to canonical ids (e.g. references' citing_id/cited_id,
    topics' work_id). Ids absent from the mapping are left unchanged."""
    if not mapping or df.empty:
        return df
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col].map(lambda x: mapping.get(x, x))
    return out
