"""Evaluation metrics for 100-class distribution forecasts."""
from __future__ import annotations

import numpy as np

N = 100
SECTION_BOUNDS = {"A": (0, 24), "B": (25, 49), "C": (50, 74), "D": (75, 99)}
SECTION_OF = np.zeros(N, dtype=int)
for i, (s, (lo, hi)) in enumerate(SECTION_BOUNDS.items()):
    SECTION_OF[lo : hi + 1] = i


def topk_hit(preds: np.ndarray, y: np.ndarray, k: int) -> float:
    hits = 0
    for p, actual in zip(preds, y):
        top = np.argsort(p)[::-1][:k]
        hits += int(actual in top)
    return hits / max(1, len(y))


def section_accuracy(preds: np.ndarray, y: np.ndarray) -> float:
    correct = 0
    for p, actual in zip(preds, y):
        pred_section = int(np.argmax(np.bincount(SECTION_OF, weights=p, minlength=4)))
        correct += int(SECTION_OF[actual] == pred_section)
    return correct / max(1, len(y))


def mean_rank(preds: np.ndarray, y: np.ndarray) -> float:
    ranks = [int((p > p[a]).sum()) + 1 for p, a in zip(preds, y)]
    return float(np.mean(ranks))


def mean_reciprocal_rank(preds: np.ndarray, y: np.ndarray) -> float:
    rr = [1.0 / ((p > p[a]).sum() + 1) for p, a in zip(preds, y)]
    return float(np.mean(rr))


def log_loss(preds: np.ndarray, y: np.ndarray, eps: float = 1e-12) -> float:
    return float(-np.mean(np.log(preds[np.arange(len(y)), y] + eps)))


def brier_score(preds: np.ndarray, y: np.ndarray) -> float:
    """Multiclass Brier over all 100 classes."""
    onehot = np.zeros_like(preds)
    onehot[np.arange(len(y)), y] = 1.0
    return float(np.mean(np.sum((preds - onehot) ** 2, axis=1)))


def calibration_curve(
    preds: np.ndarray, y: np.ndarray, n_bins: int = 10
) -> dict:
    """Reliability of predicted probabilities (binned by confidence)."""
    confidences = preds.max(axis=1)
    picks = preds.argmax(axis=1)
    correct = (picks == y).astype(float)
    bins: list[dict] = []
    edges = np.linspace(0, max(0.02, confidences.max() * 1.001), n_bins + 1)
    for i in range(n_bins):
        mask = (confidences >= edges[i]) & (confidences < edges[i + 1])
        if mask.sum() == 0:
            continue
        bins.append(
            {
                "bin_low": round(float(edges[i]), 5),
                "bin_high": round(float(edges[i + 1]), 5),
                "count": int(mask.sum()),
                "avg_confidence": float(confidences[mask].mean()),
                "empirical_accuracy": float(correct[mask].mean()),
            }
        )
    ece = sum(b["count"] / len(y) * abs(b["empirical_accuracy"] - b["avg_confidence"]) for b in bins)
    return {"bins": bins, "expected_calibration_error": float(ece)}


def confusion_sections(preds: np.ndarray, y: np.ndarray) -> dict:
    names = list(SECTION_BOUNDS.keys())
    matrix = np.zeros((4, 4), dtype=int)
    for p, actual in zip(preds, y):
        pred_section = int(np.argmax(np.bincount(SECTION_OF, weights=p, minlength=4)))
        matrix[SECTION_OF[actual], pred_section] += 1
    return {
        "labels": names,
        "rows_actual_cols_predicted": matrix.tolist(),
    }


def evaluate_all(preds: np.ndarray, y: np.ndarray) -> dict:
    return {
        "n_predictions": int(len(y)),
        "top1_hit_rate": round(topk_hit(preds, y, 1), 5),
        "top3_hit_rate": round(topk_hit(preds, y, 3), 5),
        "top5_hit_rate": round(topk_hit(preds, y, 5), 5),
        "top10_hit_rate": round(topk_hit(preds, y, 10), 5),
        "section_accuracy": round(section_accuracy(preds, y), 5),
        "mean_rank": round(mean_rank(preds, y), 2),
        "mean_reciprocal_rank": round(mean_reciprocal_rank(preds, y), 6),
        "log_loss": round(log_loss(preds, y), 6),
        "brier_score": round(brier_score(preds, y), 8),
        "uniform_log_loss_reference": round(float(-np.log(0.01)), 4),
        "calibration": calibration_curve(preds, y),
        "section_confusion": confusion_sections(preds, y),
    }


def evaluate_by_segment(
    preds: np.ndarray,
    y: np.ndarray,
    segments: np.ndarray,
) -> dict:
    """Performance grouped by arbitrary segment labels (session/month/year)."""
    out: dict[str, dict] = {}
    for seg in sorted(set(segments.tolist())):
        mask = segments == seg
        if mask.sum() >= 5:
            sub = evaluate_all(preds[mask], y[mask])
            sub.pop("calibration", None)
            sub.pop("section_confusion", None)
            out[str(seg)] = sub
    return out
