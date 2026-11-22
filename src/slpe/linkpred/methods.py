"""Topological link-prediction scores + baselines, computed on the feature network.

Core methods (Liben-Nowell & Kleinberg 2007): Common Neighbors, Jaccard,
Adamic-Adar, Preferential Attachment, plus Resource Allocation. Baselines: a random
scorer and a popularity scorer (product of concept document-frequencies). All scores
are SYMMETRIC (the semantic network is undirected). A concept absent from the feature
network has no neighbours, so topological scores fall to 0 — explicit, not dropped.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable

import networkx as nx

Pair = tuple[str, str]


def _neighbors(g: nx.Graph, n: str) -> set[str]:
    return set(g[n]) if n in g else set()


def common_neighbors(g: nx.Graph, a: str, b: str) -> float:
    return float(len(_neighbors(g, a) & _neighbors(g, b)))


def jaccard(g: nx.Graph, a: str, b: str) -> float:
    na, nb = _neighbors(g, a), _neighbors(g, b)
    union = na | nb
    return len(na & nb) / len(union) if union else 0.0


def adamic_adar(g: nx.Graph, a: str, b: str) -> float:
    total = 0.0
    for w in _neighbors(g, a) & _neighbors(g, b):
        d = g.degree(w)
        if d > 1:
            total += 1.0 / math.log(d)
    return total


def resource_allocation(g: nx.Graph, a: str, b: str) -> float:
    total = 0.0
    for w in _neighbors(g, a) & _neighbors(g, b):
        d = g.degree(w)
        if d > 0:
            total += 1.0 / d
    return total


def preferential_attachment(g: nx.Graph, a: str, b: str) -> float:
    return float((g.degree(a) if a in g else 0) * (g.degree(b) if b in g else 0))


def _doc_count(g: nx.Graph, n: str) -> int:
    return g.nodes[n].get("doc_count", 0) if n in g else 0


def popularity(g: nx.Graph, a: str, b: str) -> float:
    """Baseline: product of concept document-frequencies (concept popularity)."""
    return float(_doc_count(g, a) * _doc_count(g, b))


# Deterministic topological methods (graph, a, b) -> score.
METHODS: dict[str, Callable[[nx.Graph, str, str], float]] = {
    "common_neighbors": common_neighbors,
    "jaccard": jaccard,
    "adamic_adar": adamic_adar,
    "resource_allocation": resource_allocation,
    "preferential_attachment": preferential_attachment,
    "popularity": popularity,
}


def score_pairs(g: nx.Graph, pairs: list[Pair], method: str) -> list[float]:
    fn = METHODS[method]
    return [fn(g, a, b) for a, b in pairs]


def score_all_methods(g: nx.Graph, pairs: list[Pair], *, seed: int = 0) -> dict[str, list[float]]:
    """Score every method plus a random baseline for the given pairs."""
    scores = {name: score_pairs(g, pairs, name) for name in METHODS}
    rng = random.Random(seed)
    scores["random"] = [rng.random() for _ in pairs]
    return scores
