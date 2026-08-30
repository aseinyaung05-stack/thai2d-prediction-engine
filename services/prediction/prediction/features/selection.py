"""Feature selection — fitted ONLY on training folds (never on full data)."""
from __future__ import annotations

import numpy as np


def correlation_filter(X: np.ndarray, threshold: float = 0.90) -> list[int]:
    """Drop one feature of any pair with |corr| > threshold.

    Returns indices of kept features. Deterministic: keeps the earlier column.
    """
    if X.shape[0] < 3 or X.shape[1] == 0:
        return list(range(X.shape[1]))
    corr = np.corrcoef(X, rowvar=False)
    corr = np.nan_to_num(corr, nan=0.0)
    kept: list[int] = []
    for j in range(X.shape[1]):
        redundant = False
        for k in kept:
            if abs(corr[j, k]) > threshold:
                # Constant/near-constant columns produce NaN corr -> treat 0.
                redundant = True
                break
        if not redundant:
            kept.append(j)
    return kept or [0]


def variance_filter(X: np.ndarray, min_var: float = 1e-8) -> list[int]:
    var = np.nanvar(X, axis=0)
    return [j for j in range(X.shape[1]) if var[j] > min_var]


def mutual_information_top(X: np.ndarray, y: np.ndarray, top_k: int | None = None) -> list[int]:
    """Rank features by mutual information with the winner label."""
    from sklearn.feature_selection import mutual_info_classif

    if len(np.unique(y)) < 2:
        return list(range(X.shape[1]))
    mi = mutual_info_classif(X, y, random_state=0, discrete_features=False)
    order = np.argsort(mi)[::-1]
    k = top_k if top_k else X.shape[1]
    return sorted(int(j) for j in order[:k])


def select_features(
    X: np.ndarray, y: np.ndarray, corr_threshold: float = 0.90
) -> tuple[list[int], dict]:
    """Pipeline: variance filter -> correlation filter (multicollinearity).

    Mutual-information ranking is applied by ML models themselves via their
    own regularization; we keep selection simple, causal and auditable.
    """
    var_kept = variance_filter(X)
    Xv = X[:, var_kept]
    corr_kept_rel = correlation_filter(Xv, corr_threshold)
    final = [var_kept[i] for i in corr_kept_rel]
    meta = {
        "input_features": int(X.shape[1]),
        "after_variance": int(len(var_kept)),
        "after_correlation": int(len(final)),
        "correlation_threshold": float(corr_threshold),
    }
    return final, meta
