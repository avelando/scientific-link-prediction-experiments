"""Tests for the concept->network->pairs->linkpred->metrics pipeline (synthetic)."""

import math

import networkx as nx

from slpe.concepts.extract import extract_document_concepts, normalize_concept
from slpe.eval.metrics import auprc, evaluate_method, precision_at_k, recall_at_k
from slpe.linkpred.methods import (
    adamic_adar,
    common_neighbors,
    jaccard,
    preferential_attachment,
    resource_allocation,
    score_all_methods,
)
from slpe.networks.novelty import NoveltyLedger
from slpe.networks.semantic import build_semantic_network, cooccurrence_counts, network_stats
from slpe.pairs.candidates import (
    emergent_positive_pairs,
    enumerate_candidate_pairs,
    sample_candidate_pairs,
)

# --- concepts -------------------------------------------------------------

def test_normalize_concept():
    assert normalize_concept("Graph Neural Networks") == "graph neural network"
    assert normalize_concept("the results") is None      # generic
    assert normalize_concept("  Deep-Learning!! ") == "deep-learning"
    assert normalize_concept("123") is None


def test_normalization_preserves_scientific_terms():
    # Regression (audit): these must NOT be over-singularized.
    assert normalize_concept("physics") == "physics"
    assert normalize_concept("numerical analysis") == "numerical analysis"  # not "analysi"
    assert normalize_concept("time series") == "time series"      # not "time sery"
    assert normalize_concept("quantum mechanics") == "quantum mechanics"
    assert normalize_concept("species") == "species"
    assert normalize_concept("kinetics") == "kinetics"
    # genuine plurals still reduce
    assert normalize_concept("neural networks") == "neural network"
    assert normalize_concept("categories") == "category"


def test_extract_document_concepts_real_yake():
    concepts = extract_document_concepts(
        "Graph neural networks for link prediction",
        "We study link prediction in citation networks using graph neural networks.",
        top_k=8,
    )
    assert concepts  # non-empty
    assert all(c == normalize_concept(c) for c in concepts)  # already normalized
    assert len(concepts) == len(set(concepts))              # de-duplicated


# --- network --------------------------------------------------------------

def test_cooccurrence_and_network():
    docs = {"d1": ["a", "b", "c"], "d2": ["a", "b"], "d3": ["c", "d"]}
    pairs, concept_counts = cooccurrence_counts(docs)
    assert pairs[frozenset(("a", "b"))] == 2   # a,b together in d1,d2
    assert concept_counts["a"] == 2
    g = build_semantic_network(docs)
    assert g.number_of_nodes() == 4
    assert g["a"]["b"]["weight"] == 2
    stats = network_stats(g)
    assert stats["n_nodes"] == 4 and stats["n_edges"] >= 3


# --- novelty ledger -------------------------------------------------------

def test_novelty_ledger():
    ledger = NoveltyLedger()
    ledger.add_documents({"d1": ["a", "b"], "d2": ["b", "c"]})
    assert ledger.has_cooccurred("a", "b")
    assert not ledger.has_cooccurred("a", "c")
    assert ledger.is_candidate("a", "c")       # both known, never co-occurred
    assert not ledger.is_candidate("a", "b")   # already co-occurred
    assert not ledger.is_candidate("a", "z")   # z unknown


# --- candidate pairs ------------------------------------------------------

def test_emergent_positives_and_sampling():
    ledger = NoveltyLedger()
    ledger.add_documents({"h1": ["a", "b"], "h2": ["c", "d"], "h3": ["a", "c"]})
    # Future: a & d co-occur (novel at T); a & b co-occur (NOT novel, already seen).
    future = {"f1": ["a", "d"], "f2": ["a", "b"]}
    positives = emergent_positive_pairs(future, ledger)
    assert frozenset(("a", "d")) in positives
    assert frozenset(("a", "b")) not in positives     # not a novelty candidate

    g = build_semantic_network({"h1": ["a", "b"], "h2": ["c", "d"], "h3": ["a", "c"]})
    sample = sample_candidate_pairs(ledger, g, positives, n_negatives=5, seed=1)
    labels = {frozenset((p.a, p.b)): p.label for p in sample}
    assert labels[frozenset(("a", "d"))] == 1          # positive kept
    assert all(p.label in (0, 1) for p in sample)
    # every pair is a true novelty candidate (symmetric, never co-occurred)
    assert all(ledger.is_candidate(p.a, p.b) for p in sample)


def test_exhaustive_candidate_universe():
    ledger = NoveltyLedger()
    ledger.add_documents({"h1": ["a", "b"], "h2": ["c", "d"], "h3": ["a", "c"]})
    # Known concepts: a,b,c,d. Co-occurred pairs: ab, cd, ac. Eligible (candidate)
    # pairs: ad, bc, bd  -> 3 total.
    positives = emergent_positive_pairs({"f": ["a", "d"]}, ledger)
    g = build_semantic_network({"h1": ["a", "b"], "h2": ["c", "d"], "h3": ["a", "c"]})
    universe = enumerate_candidate_pairs(ledger, g, positives)
    keys = {frozenset((p.a, p.b)) for p in universe}
    assert keys == {frozenset(("a", "d")), frozenset(("b", "c")), frozenset(("b", "d"))}
    # exactly the one positive, real prevalence = 1/3
    assert sum(p.label for p in universe) == 1
    assert all(p.inclusion_prob == 1.0 for p in universe)       # population = sample
    assert all(not ledger.has_cooccurred(p.a, p.b) for p in universe)


def test_enumerate_returns_none_when_too_large():
    ledger = NoveltyLedger()
    ledger.add_documents({f"d{i}": [f"c{i}", f"c{i+1}"] for i in range(50)})
    g = build_semantic_network({f"d{i}": [f"c{i}", f"c{i+1}"] for i in range(50)})
    assert enumerate_candidate_pairs(ledger, g, set(), max_candidates=10) is None


# --- link-prediction methods ---------------------------------------------

def test_linkpred_methods_known_values():
    g = nx.Graph()
    g.add_edges_from([("a", "c"), ("b", "c"), ("a", "d"), ("b", "d")])
    assert common_neighbors(g, "a", "b") == 2.0        # c and d
    assert jaccard(g, "a", "b") == 1.0                  # identical neighbourhoods
    assert resource_allocation(g, "a", "b") == 1.0      # 1/2 + 1/2
    assert preferential_attachment(g, "a", "b") == 4.0  # 2 * 2
    assert abs(adamic_adar(g, "a", "b") - 2 / math.log(2)) < 1e-9
    # Absent concept -> zero, not error.
    assert common_neighbors(g, "a", "zzz") == 0.0


def test_score_all_methods_symmetric():
    g = nx.Graph()
    g.add_edges_from([("a", "c"), ("b", "c")])
    s1 = score_all_methods(g, [("a", "b")], seed=0)
    s2 = score_all_methods(g, [("b", "a")], seed=0)
    for m in ("common_neighbors", "jaccard", "adamic_adar"):
        assert s1[m] == s2[m]  # symmetric features


# --- metrics --------------------------------------------------------------

def test_metrics_known_values():
    labels = [1, 0, 1, 0]
    scores = [0.9, 0.8, 0.7, 0.1]   # ranked: idx0(1), idx1(0), idx2(1), idx3(0)
    assert precision_at_k(labels, scores, 2) == 0.5   # 1 of top-2
    assert recall_at_k(labels, scores, 2) == 0.5      # 1 of 2 positives
    assert precision_at_k(labels, scores, 4) == 0.5
    assert recall_at_k(labels, scores, 4) == 1.0
    assert auprc(labels, scores) > 0.0
    report = evaluate_method(labels, scores, ks=(2,))
    assert report["n_positives"] == 2 and report["prevalence"] == 0.5


def test_auprc_handles_no_positives():
    assert auprc([0, 0, 0], [0.1, 0.2, 0.3]) == 0.0


def test_precision_at_k_constant_scores_equals_prevalence():
    # The bug: positives listed first + tied (zero) scores -> P@K inflated to 1.0.
    # Fixed: expected P@K under tie-breaking equals prevalence for a constant scorer.
    labels = [1, 1, 1, 0, 0, 0, 0, 0, 0, 0]   # 3 positives, listed first
    scores = [0.0] * 10                         # all tied
    prevalence = 0.3
    assert abs(precision_at_k(labels, scores, 5) - prevalence) < 1e-9
    assert abs(precision_at_k(labels, scores, 10) - prevalence) < 1e-9
    assert abs(recall_at_k(labels, scores, 5) - (5 * prevalence / 3)) < 1e-9


def test_metrics_invariant_to_candidate_permutation():
    import random
    labels = [1, 0, 1, 0, 0, 1, 0, 0, 1, 0]
    scores = [0.5, 0.5, 0.2, 0.9, 0.2, 0.5, 0.1, 0.9, 0.2, 0.5]  # many ties
    base_p = precision_at_k(labels, scores, 4)
    base_r = recall_at_k(labels, scores, 4)
    base_ap = auprc(labels, scores)
    rng = random.Random(7)
    for _ in range(20):
        perm = list(range(len(labels)))
        rng.shuffle(perm)
        pl = [labels[i] for i in perm]
        ps = [scores[i] for i in perm]
        assert abs(precision_at_k(pl, ps, 4) - base_p) < 1e-9
        assert abs(recall_at_k(pl, ps, 4) - base_r) < 1e-9
        assert abs(auprc(pl, ps) - base_ap) < 1e-9
