"""Build the semantic corpus from collected publications, with exclusion stats.

The semantic corpus keeps publications with a title, a reconstructable English
abstract and a usable date — the basis for later concept extraction and the
semantic network. Abstracts are preserved as reconstructed (no destructive
normalization here). Anomalies are counted and excluded transparently, never
silently dropped. OpenAlex topics remain for delimitation only; they are not
concepts/vertices.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class CorpusStats:
    n_input: int
    n_included: int
    exclusions: dict[str, int]  # reason -> count

    def coverage(self) -> float:
        return self.n_included / self.n_input if self.n_input else 0.0


def build_semantic_corpus(
    pub_df: pd.DataFrame,
    *,
    min_tokens: int = 20,
    require_language_en: bool = True,
) -> tuple[pd.DataFrame, CorpusStats]:
    """Filter publications into the semantic corpus and report exclusions.

    Exclusion reasons (evaluated in priority order, one per excluded row):
        no_title, no_abstract, short_abstract (< min_tokens), not_english, no_date.
    """
    import pandas as pd

    n_input = len(pub_df)
    if n_input == 0:
        return pub_df.copy(), CorpusStats(0, 0, {})

    df = pub_df.copy()
    reason = pd.Series(pd.NA, index=df.index, dtype="object")

    def mark(mask, label):
        unset = reason.isna()
        reason.loc[unset & mask] = label

    mark(df["title"].isna() | (df["title"].astype(str).str.strip() == ""), "no_title")
    mark(df["abstract"].isna(), "no_abstract")
    mark(df["abstract_tokens"].fillna(0) < min_tokens, "short_abstract")
    if require_language_en:
        mark(df["language"] != "en", "not_english")
    mark(df["publication_date"].isna() & df["publication_year"].isna(), "no_date")

    included = df[reason.isna()].copy()
    excluded = reason[reason.notna()]
    exclusions = excluded.value_counts().to_dict()
    stats = CorpusStats(n_input=n_input, n_included=len(included),
                        exclusions={str(k): int(v) for k, v in exclusions.items()})
    return included, stats
