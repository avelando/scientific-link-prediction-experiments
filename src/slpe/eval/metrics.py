"""Ranking metrics for link prediction: AUPRC, Precision@K, Recall@K.

Metrics are computed over the evaluation candidate set (positives + sampled
negatives). Because negatives are sampled, these are CONDITIONAL on the evaluation
set, not population estimates — reported prevalence and coverage make that explicit.
Ties in scores are broken deterministically (stable sort) so results are reproducible.
"""

from __future__ import annotations

from collections.abc import Sequence


def auprc(labels: Sequence[int], scores: Sequence[float]) -> float:
    """Area under the precision-recall curve (average precision)."""
    if not labels or sum(labels) == 0:
        return 0.0
    from sklearn.metrics import average_precision_score

    return float(average_precision_score(list(labels), list(scores)))


def _rank_desc(scores: Sequence[float]) -> list[int]:
    # Stable descending order by score (ties keep input order).
    return sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)


def precision_at_k(labels: Sequence[int], scores: Sequence[float], k: int) -> float:
    if k <= 0 or not labels:
        return 0.0
    order = _rank_desc(scores)[:k]
    hits = sum(labels[i] for i in order)
    return hits / min(k, len(labels))


def recall_at_k(labels: Sequence[int], scores: Sequence[float], k: int) -> float:
    total_pos = sum(labels)
    if total_pos == 0 or k <= 0:
        return 0.0
    order = _rank_desc(scores)[:k]
    hits = sum(labels[i] for i in order)
    return hits / total_pos


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
