"""Ensemble with validation-optimized weights + temperature calibration.

Weights are learned on the VALIDATION fold only (never test, never train).
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize

from .base import DistributionModel, normalize_distribution


def model_input(m: DistributionModel, X_full: np.ndarray, sel_idx) -> np.ndarray:
    """Statistical models read named columns from the FULL matrix; only
    ML models (needs_feature_selection) receive the training-fold slice."""
    if getattr(m, "needs_feature_selection", False) and sel_idx is not None:
        return X_full[:, sel_idx]
    return X_full


def _mix_loglinear(weights: np.ndarray, stack: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Log-linear pooling: mix ∝ Π p_i^{w_i}, normalized over the last axis.

    `stack` is (n_groups, n_components, 100); weights is (n_components,).
    Contract the component axis explicitly — tensordot(axes=1) would pair
    against axis 0 (groups) and raise a shape error.
    """
    logs = np.log(stack + eps)
    mix = np.exp(np.tensordot(weights, logs, axes=([0], [1])))
    mix /= mix.sum(axis=-1, keepdims=True)
    return mix


class EnsembleModel(DistributionModel):
    """Weighted log-linear combination of component distributions.

        score ∝ Π p_i^{w_i}  (log-space linear pooling)

    Log-space pooling is less prone to a single overconfident component
    dominating and keeps the mixture strictly positive.
    """

    name = "ensemble"

    def __init__(self, components: list[DistributionModel]):
        self.components = components
        self.weights = np.full(len(components), 1.0 / max(1, len(components)))

    def fit_weights(self, component_preds: np.ndarray, y_true: np.ndarray) -> np.ndarray:
        """Optimize simplex weights minimizing validation log loss.

        component_preds: (n_groups, n_components, 100)
        y_true:          (n_groups,) actual number per group.
        """
        n_comp = len(self.components)
        if len(y_true) < 30 or n_comp == 0:
            return self.weights

        eps = 1e-12
        logs = np.log(component_preds + eps)              # (G, C, 100)

        def loss(w: np.ndarray) -> float:
            w = np.clip(w, 0, None)
            if w.sum() <= 0:
                return 1e6
            w = w / w.sum()
            mix = np.exp(np.tensordot(w, logs, axes=([0], [1])))   # (G, 100)
            mix /= mix.sum(axis=1, keepdims=True)
            nll = -np.log(mix[np.arange(len(y_true)), y_true] + eps)
            val = nll.mean()
            # Tiny L2 toward uniform to avoid degenerate all-in-one-component.
            return float(val + 1e-4 * float(((w - 1 / n_comp) ** 2).sum()))

        x0 = np.full(n_comp, 1.0 / n_comp)
        res = minimize(loss, x0, method="SLSQP",
                       bounds=[(0.0, 1.0)] * n_comp,
                       constraints={"type": "eq", "fun": lambda w: w.sum() - 1},
                       options={"maxiter": 200, "ftol": 1e-7})
        w = np.clip(res.x if res.success else x0, 0, None)
        if w.sum() > 0:
            self.weights = w / w.sum()
        return self.weights

    def predict(self, X, sel_idx=None) -> np.ndarray:
        """Combine components into one distribution for one snapshot.

        Accepts EITHER the candidate feature matrix (100, F) — components are
        evaluated internally — OR an explicit stack/list of component
        distributions (C, 100). Components that declare
        `needs_feature_selection` receive the selected-feature slice.
        """
        if isinstance(X, np.ndarray) and X.ndim == 2:
            preds = [
                normalize_distribution(m.predict(model_input(m, X, sel_idx)))
                for m in self.components
            ]
            stack = np.asarray(preds)
        else:
            stack = np.asarray([normalize_distribution(p) for p in X])
        return _mix_loglinear(self.weights, stack[np.newaxis, ...])[0]


class TemperatureScaler:
    """Distribution calibration via a single temperature parameter.

    Fitted ONLY on validation data (never the untouched test set).
    Stores raw_probability vs calibrated_probability separately.
    """

    def __init__(self):
        self.temperature = 1.0

    def fit(self, preds: np.ndarray, y_true: np.ndarray) -> float:
        eps = 1e-12
        logs = np.log(preds + eps)

        def nll(log_T: float) -> float:
            T = np.exp(log_T)
            scaled = np.exp(logs / T)
            scaled /= scaled.sum(axis=1, keepdims=True)
            return float(-np.log(scaled[np.arange(len(y_true)), y_true] + eps).mean())

        from scipy.optimize import minimize_scalar

        res = minimize_scalar(nll, bounds=(np.log(0.25), np.log(4.0)), method="bounded")
        self.temperature = float(np.exp(res.x))
        return self.temperature

    def transform(self, p: np.ndarray) -> np.ndarray:
        scaled = np.power(np.asarray(p, dtype=float) + 1e-12, 1.0 / self.temperature)
        return normalize_distribution(scaled)
