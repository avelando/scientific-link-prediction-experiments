"""Semantic co-occurrence network (undirected, weighted).

Vertices are concepts; an edge connects two concepts that co-occur in the same
document; the edge weight is the number of documents in which the pair co-occurs
(project §4.1). Built per area and per temporal cut from a document->concepts map.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from itertools import combinations

import networkx as nx


def cooccurrence_counts(
    doc_concepts: Mapping[str, Iterable[str]]
) -> tuple[Counter, Counter]:
    """Return (pair_counts, concept_doc_counts).

    pair_counts: {frozenset({a, b}): #docs with both}.
    concept_doc_counts: {concept: #docs containing it}.
    """
    pair_counts: Counter = Counter()
    concept_counts: Counter = Counter()
    for concepts in doc_concepts.values():
        unique = sorted(set(concepts))
        for c in unique:
            concept_counts[c] += 1
        for a, b in combinations(unique, 2):
            pair_counts[frozenset((a, b))] += 1
    return pair_counts, concept_counts


def build_semantic_network(
    doc_concepts: Mapping[str, Iterable[str]],
    *,
    min_concept_docs: int = 1,
    min_edge_weight: int = 1,
) -> nx.Graph:
    """Build the weighted undirected semantic network.

    Args:
        min_concept_docs: drop concepts appearing in fewer than this many documents.
        min_edge_weight: drop edges with weight below this threshold.
    """
    pair_counts, concept_counts = cooccurrence_counts(doc_concepts)
    keep = {c for c, n in concept_counts.items() if n >= min_concept_docs}

    g = nx.Graph()
    for c in keep:
        g.add_node(c, doc_count=concept_counts[c])
    for pair, w in pair_counts.items():
        if w < min_edge_weight:
            continue
        a, b = tuple(pair)
        if a in keep and b in keep:
            g.add_edge(a, b, weight=w)
    return g


def network_stats(g: nx.Graph) -> dict:
    """Basic structural statistics of a semantic network."""
    n, m = g.number_of_nodes(), g.number_of_edges()
    degrees = [d for _, d in g.degree()]
    components = list(nx.connected_components(g)) if n else []
    giant = max((len(c) for c in components), default=0)
    density = (2 * m / (n * (n - 1))) if n > 1 else 0.0
    return {
        "n_nodes": n,
        "n_edges": m,
        "density": round(density, 6),
        "n_components": len(components),
        "giant_component_frac": round(giant / n, 4) if n else 0.0,
        "mean_degree": round(sum(degrees) / n, 3) if n else 0.0,
        "max_degree": max(degrees, default=0),
    }
