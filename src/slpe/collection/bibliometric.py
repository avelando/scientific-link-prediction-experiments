"""Prepare bibliometric data (reference edges) without computing disruption.

Stores the directed citation edges (citing -> cited) needed to later build the
citation network and disruption index. Key constraints (project §4.1, §4.4):

    * Edge orientation is citing -> cited (the citing work holds the reference).
    * CURRENT cumulative citation counts are NOT used as historical features;
      only the reference EDGES are kept, to be time-sliced later by publication date.
    * External references (outside the focal field) are preserved — disruption may
      depend on citations from other fields.

This module validates/organizes edges; it does NOT compute any bibliometric index.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class EdgeStats:
    n_edges: int
    n_citing: int          # distinct citing works
    n_cited: int           # distinct cited works
    n_internal: int        # edges whose cited work is within the focal set
    n_external: int        # edges whose cited work is outside the focal set


def citation_edges(refs_df: pd.DataFrame) -> pd.DataFrame:
    """Return validated, de-duplicated directed edges (citing_id -> cited_id)."""
    import pandas as pd

    if refs_df.empty:
        return pd.DataFrame(columns=["citing_id", "cited_id"])
    edges = refs_df.dropna(subset=["citing_id", "cited_id"])
    edges = edges[edges["citing_id"] != edges["cited_id"]]  # no self-citations
    return edges.drop_duplicates(subset=["citing_id", "cited_id"]).reset_index(drop=True)


def edge_stats(edges: pd.DataFrame, focal_ids: set[str]) -> EdgeStats:
    """Summarize edges, distinguishing internal vs external cited works.

    External references are RETAINED (not filtered); this only reports the split.
    """
    if edges.empty:
        return EdgeStats(0, 0, 0, 0, 0)
    cited_internal = edges["cited_id"].isin(focal_ids)
    return EdgeStats(
        n_edges=len(edges),
        n_citing=edges["citing_id"].nunique(),
        n_cited=edges["cited_id"].nunique(),
        n_internal=int(cited_internal.sum()),
        n_external=int((~cited_internal).sum()),
    )
