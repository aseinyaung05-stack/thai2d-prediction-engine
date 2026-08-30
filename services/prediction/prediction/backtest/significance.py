"""Statistical significance of model-vs-baseline improvement.

Small-sample differences must not be presented as "model is better"
(spec: STATISTICAL SIGNIFICANCE). We use a paired bootstrap over prediction
events plus a binomial-style z-test for top-k hit-rate differences.
"""
from __future__ import annotations

import math

import numpy as np


def paired_bootstrap_ci(
    metric_a: np.ndarray,
    metric_b: np.ndarray,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> dict:
    """CI for mean(metric_a - metric_b) via paired bootstrap.

    metric_a/b are per-event scores (e.g., 1/0 top-k hit or per-event logloss).
    """
    assert len(metric_a) == len(metric_b)
    diff = metric_a - metric_b
    rng = np.random.default_rng(seed)
    n = len(diff)
    if n == 0:
        return {"mean_diff": 0.0, "ci_low": 0.0, "ci_high": 0.0, "n": 0}
    boots = np.array(
        [diff[rng.integers(0, n, n)].mean() for _ in range(n_boot)]
    )
    lo, hi = np.quantile(boots, [alpha / 2, 1 - alpha / 2])
    return {
        "mean_diff": float(diff.mean()),
        "ci_low": float(lo),
        "ci_high": float(hi),
        "n": int(n),
        "significant_at_alpha": bool(lo > 0 or hi < 0),
        "alpha": alpha,
    }


def binomial_z_test(k_a: int, n_a: int, p_b: float) -> dict:
    """One-sample z-test: does A's hit count exceed baseline rate p_b?"""
    if n_a == 0:
        return {"z": 0.0, "p_value_one_sided": 0.5, "n": 0}
    p_hat = k_a / n_a
    se = math.sqrt(p_b * (1 - p_b) / n_a)
    if se == 0:
        return {"z": 0.0, "p_value_one_sided": 0.5, "n": n_a}
    z = (p_hat - p_b) / se
    from scipy.stats import norm

    p_one = float(1 - norm.cdf(z))
    return {"z": round(z, 3), "p_value_one_sided": round(p_one, 5), "n": n_a}


def compare_topk_to_baseline(
    hits_a: np.ndarray, hits_b: np.ndarray, baseline_rate: float
) -> dict:
    k_a = int(hits_a.sum())
    n = int(len(hits_a))
    boot = paired_bootstrap_ci(hits_a.astype(float), hits_b.astype(float))
    ztest = binomial_z_test(k_a, n, baseline_rate)
    return {
        "model_hits": k_a,
        "baseline_hits": int(hits_b.sum()),
        "n_predictions": n,
        "bootstrap": boot,
        "binomial_vs_theoretical_baseline": ztest,
    }
