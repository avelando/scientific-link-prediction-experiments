"""Ranking metrics for link prediction: AUPRC, Precision@K, Recall@K.

CRITICAL — tie handling. A naive top-K that breaks ties by input order inflates
Precision@K whenever positives are listed before negatives and many scores tie
(e.g. zeros): a constant scorer would score Precision@100 = 1.0. To remove that
bias, Precision@K and Recall@K here are the **expected** values under a uniformly
random shuffle of tied scores (closed form), which depends ONLY on the scores and
labels — never on the input order. A constant scorer therefore yields
Precision@K = prevalence, and the metric is invariant to permuting the candidates.

AUPRC uses scikit-learn's ``average_precision_score`` (a proper step-wise estimator,
not trapezoidal interpolation of the PR curve).
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import groupby


def auprc(labels: Sequence[int], scores: Sequence[float]) -> float:
    """Area under the precision-recall curve (average precision)."""
    if not labels or sum(labels) == 0:
        return 0.0
    from sklearn.metrics import average_precision_score

    return float(average_precision_score(list(labels), list(scores)))


def _expected_hits_at_k(labels: Sequence[int], scores: Sequence[float], k: int) -> float:
    """Expected #positives in the top K under random tie-breaking (closed form).

    Groups candidates by equal score (descending). Whole groups that fit entirely
    within K contribute all their positives; the group straddling the K boundary
    contributes its positives scaled by the fraction of its members that fall inside
    K (= expected count under a uniform random order within the tie group).
    """
    k = min(k, len(labels))
    if k <= 0:
        return 0.0
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    hits = 0.0
    filled = 0
    for _score, grp in groupby(order, key=lambda i: scores[i]):
        idx = list(grp)
        size = len(idx)
        pos = sum(labels[i] for i in idx)
        if filled + size <= k:
            hits += pos
            filled += size
        else:
            remaining = k - filled
            hits += pos * (remaining / size)  # expected positives among the slots taken
            filled = k
            break
    return hits


def precision_at_k(labels: Sequence[int], scores: Sequence[float], k: int) -> float:
    """Expected Precision@K under random tie-breaking (order-independent)."""
    if k <= 0 or not labels:
        return 0.0
    denom = min(k, len(labels))
    return _expected_hits_at_k(labels, scores, k) / denom


def recall_at_k(labels: Sequence[int], scores: Sequence[float], k: int) -> float:
    """Expected Recall@K under random tie-breaking (order-independent)."""
    total_pos = sum(labels)
    if total_pos == 0 or k <= 0:
        return 0.0
    return _expected_hits_at_k(labels, scores, k) / total_pos


def evaluate_method(
    labels: Sequence[int], scores: Sequence[float], ks: Sequence[int] = (10, 50, 100)
) -> dict:
    """Return AUPRC + Precision@K / Recall@K for each K, plus prevalence/coverage."""
    out: dict[str, float] = {
        "auprc": round(auprc(labels, scores), 5),
        "n_candidates": len(labels),
        "n_positives": int(sum(labels)),
        "prevalence": round(sum(labels) / len(labels), 5) if labels else 0.0,
    }
    for k in ks:
        out[f"precision_at_{k}"] = round(precision_at_k(labels, scores, k), 5)
        out[f"recall_at_{k}"] = round(recall_at_k(labels, scores, k), 5)
    return out


def stratified_by(
    strata: Sequence, labels: Sequence[int], scores: Sequence[float],
    ks: Sequence[int] = (10, 50)
) -> dict:
    """Evaluate within each stratum value (e.g. distance bucket, same/diff community)."""
    groups: dict = {}
    for s, y, sc in zip(strata, labels, scores, strict=False):
        groups.setdefault(s, ([], []))
        groups[s][0].append(y)
        groups[s][1].append(sc)
    return {str(key): evaluate_method(ys, scs, ks) for key, (ys, scs) in sorted(groups.items())}
