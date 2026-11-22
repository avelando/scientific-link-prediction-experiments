"""Generate candidate concept pairs and their emergence labels.

Unit of analysis: an unordered pair of concepts known at cut T that has NEVER
co-occurred in the observed history up to T (project §4.2). A pair is POSITIVE if
the two concepts co-occur in at least one document of the emergence window
(T, T+Delta_e]; NEGATIVE otherwise (absence is not "impossible", just unobserved).

Full enumeration of non-co-occurred pairs is quadratic, so negatives are sampled.
All positives are kept; negatives are a uniform random sample whose inclusion
probability is recorded, and the SAME candidate set + labels are used by every
method. Pairs whose concepts are absent/disconnected in the feature network are
kept (not silently dropped) and flagged, so disconnected-component behaviour is
explicit.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import networkx as nx

from slpe.networks.novelty import NoveltyLedger


@dataclass
class CandidatePair:
    a: str
    b: str
    label: int                 # 1 emergent, 0 not
    inclusion_prob: float       # 1.0 for positives; sampling rate for negatives
    distance: int               # topological distance in feature net (-1 = disconnected/absent)
    same_community: bool | None  # None when either concept absent from feature net


def emergent_positive_pairs(
    future_doc_concepts: Mapping[str, Iterable[str]],
    ledger: NoveltyLedger,
) -> set[frozenset]:
    """Pairs co-occurring in the future window that were novelty candidates at T."""
    from itertools import combinations

    positives: set[frozenset] = set()
    for concepts in future_doc_concepts.values():
        unique = sorted(set(concepts))
        for a, b in combinations(unique, 2):
            if ledger.is_candidate(a, b):
                positives.add(frozenset((a, b)))
    return positives


def pair_distance(g: nx.Graph, a: str, b: str, *, cutoff: int = 4) -> int:
    """Shortest-path distance in ``g`` up to ``cutoff``; -1 if absent/too far."""
    if a not in g or b not in g:
        return -1
    try:
        d = nx.shortest_path_length(g, a, b)
        return d if d <= cutoff else cutoff + 1
    except nx.NetworkXNoPath:
        return -1


def _community_map(g: nx.Graph) -> dict[str, int]:
    """Fast community assignment via label propagation (empty graph -> {})."""
    if g.number_of_nodes() == 0:
        return {}
    comms = nx.community.label_propagation_communities(g)
    return {node: i for i, comm in enumerate(comms) for node in comm}


def _all_distances(g: nx.Graph, cutoff: int) -> dict[str, dict[str, int]]:
    """Precompute bounded shortest-path distances from every node (BFS per node)."""
    return {
        n: dict(nx.single_source_shortest_path_length(g, n, cutoff=cutoff))
        for n in g.nodes()
    }


def enumerate_candidate_pairs(
    ledger: NoveltyLedger,
    feature_graph: nx.Graph,
    positives: set[frozenset],
    *,
    eligible_concepts: set[str] | None = None,
    distance_cutoff: int = 4,
    max_candidates: int = 2_000_000,
) -> list[CandidatePair] | None:
    """Exhaustively enumerate EVERY eligible candidate pair (the full universe).

    The candidate universe is the set of unordered pairs among ``eligible_concepts``
    (default: all concepts known at T) that never co-occurred in the observed history.
    Each is labelled positive iff it is in ``positives``. This removes the negative-
    sampling artifact: all methods see the same complete universe, with real
    prevalence. Returns ``None`` if the number of pairs would exceed ``max_candidates``
    (caller should then sample). ``eligible_concepts`` lets the caller apply a
    frequency floor (e.g. concepts appearing in >= k historical documents) so the
    universe is both tractable and reliable.

    Inclusion probability is 1.0 for every pair (the sample IS the population).
    """
    from itertools import combinations

    base = ledger.concepts if eligible_concepts is None else (ledger.concepts & set(eligible_concepts))
    concepts = sorted(base)
    n = len(concepts)
    if n * (n - 1) // 2 > max_candidates:
        return None

    comm = _community_map(feature_graph)
    dist = _all_distances(feature_graph, distance_cutoff)

    def distance(a: str, b: str) -> int:
        if a not in feature_graph or b not in feature_graph:
            return -1
        d = dist.get(a, {}).get(b)
        return d if d is not None else -1

    out: list[CandidatePair] = []
    for a, b in combinations(concepts, 2):
        if ledger.has_cooccurred(a, b):   # co-occurred before T -> not eligible
            continue
        label = 1 if frozenset((a, b)) in positives else 0
        same = (comm[a] == comm[b]) if (a in comm and b in comm) else None
        out.append(CandidatePair(a, b, label, 1.0, distance(a, b), same))
    if len(out) > max_candidates:
        return None
    return out


def sample_candidate_pairs(
    ledger: NoveltyLedger,
    feature_graph: nx.Graph,
    positives: set[frozenset],
    *,
    n_negatives: int,
    seed: int = 0,
    distance_cutoff: int = 4,
) -> list[CandidatePair]:
    """Build the evaluation set: all positives + a sampled set of negatives.

    Negatives are drawn uniformly at random from novelty-candidate pairs that are
    not positive. The inclusion probability recorded for negatives is the sampling
    rate over the estimated negative population.
    """
    rng = random.Random(seed)
    concepts = sorted(ledger.concepts)
    comm = _community_map(feature_graph)

    def make(a: str, b: str, label: int, incl: float) -> CandidatePair:
        dist = pair_distance(feature_graph, a, b, cutoff=distance_cutoff)
        if a in comm and b in comm:
            same = comm[a] == comm[b]
        else:
            same = None
        return CandidatePair(a, b, label, incl, dist, same)

    out: list[CandidatePair] = [make(*tuple(p), 1, 1.0) for p in positives]

    # Estimated negative population: all novelty-candidate pairs minus positives.
    n_concepts = len(concepts)
    total_pairs = n_concepts * (n_concepts - 1) // 2
    est_negatives = max(total_pairs - ledger.n_pairs - len(positives), 1)
    incl_prob = min(1.0, n_negatives / est_negatives)

    seen: set[frozenset] = set(positives)
    negatives: list[CandidatePair] = []
    attempts = 0
    max_attempts = n_negatives * 50
    while len(negatives) < n_negatives and attempts < max_attempts and n_concepts > 1:
        attempts += 1
        a, b = rng.sample(concepts, 2)
        key = frozenset((a, b))
        if key in seen or not ledger.is_candidate(a, b):
            continue
        seen.add(key)
        negatives.append(make(a, b, 0, incl_prob))

    out.extend(negatives)
    return out
