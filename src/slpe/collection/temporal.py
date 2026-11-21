"""Temporal separation: assign works to a cut's ranges and enforce no leakage.

For a cut T with history window L and emergence horizon Delta_e (config):
    * novelty history   = [full_history_start, T]   (all observed past)
    * feature window    = [history_start, T]          (recent L years)
    * emergence window  = (T, T + Delta_e]            (future labels)

No work published after T may enter predictor information for that cut. Works in the
emergence window are kept SEPARATELY as potential future labels. Reconstruction from
current OpenAlex metadata is only an approximation of the historical state, so runs
are retrospective, not strictly ex ante (recorded in manifests).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from slpe.config import TemporalConfig, TemporalCut

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class CutPartition:
    cut_name: str
    predictor: pd.DataFrame   # year <= T (usable for features/novelty)
    emergence: pd.DataFrame   # T < year <= T + Delta_e (future labels)
    future_other: pd.DataFrame  # year > T + Delta_e (not used yet)


def partition_by_cut(
    pub_df: pd.DataFrame, temporal: TemporalConfig, cut: TemporalCut
) -> CutPartition:
    """Split publications into predictor / emergence / later-future by year."""
    year = pub_df["publication_year"]
    e_start, e_end = temporal.emergence_range(cut)
    predictor = pub_df[year <= cut.cut]
    emergence = pub_df[(year >= e_start) & (year <= e_end)]
    future_other = pub_df[year > e_end]
    return CutPartition(cut.name, predictor, emergence, future_other)


def assert_no_leakage(predictor_df: pd.DataFrame, cut: TemporalCut) -> list[str]:
    """Return violations: predictor rows published after the cut T."""
    leaked = predictor_df[predictor_df["publication_year"] > cut.cut]
    if len(leaked):
        return [f"{len(leaked)} predictor rows with publication_year > T={cut.cut}"]
    return []


def tag_ranges(pub_df: pd.DataFrame, temporal: TemporalConfig, cut: TemporalCut) -> pd.DataFrame:
    """Add boolean columns marking each work's membership in the cut's ranges."""
    out = pub_df.copy()
    y = out["publication_year"]
    nov_lo, nov_hi = temporal.novelty_range(cut)
    feat_lo, feat_hi = temporal.feature_range(cut)
    em_lo, em_hi = temporal.emergence_range(cut)
    out[f"{cut.name}__in_novelty"] = (y >= nov_lo) & (y <= nov_hi)
    out[f"{cut.name}__in_feature"] = (y >= feat_lo) & (y <= feat_hi)
    out[f"{cut.name}__in_emergence"] = (y >= em_lo) & (y <= em_hi)
    return out
