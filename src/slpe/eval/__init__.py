"""Evaluation metrics for link prediction (project §4.5)."""

from slpe.eval.metrics import (
    auprc,
    evaluate_method,
    precision_at_k,
    recall_at_k,
    stratified_by,
)

__all__ = ["auprc", "evaluate_method", "precision_at_k", "recall_at_k", "stratified_by"]
