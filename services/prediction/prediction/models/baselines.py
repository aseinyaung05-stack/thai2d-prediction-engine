"""Baseline + statistical models.

BASELINE-FIRST PRINCIPLE: uniform & frequency baselines are mandatory
comparison points; advanced models must beat them out-of-sample to matter.
"""
from __future__ import annotations

import numpy as np

from .base import DistributionModel, N_NUMBERS, col, normalize_distribution


class UniformModel(DistributionModel):
    name = "uniform"

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.full(N_NUMBERS, 1.0 / N_NUMBERS)


class FrequencyModel(DistributionModel):
    """Long-window empirical frequency (baseline)."""

    name = "frequency"

    def predict(self, X: np.ndarray) -> np.ndarray:
        return normalize_distribution(col(X, "freq_250"))


class RecentFrequencyModel(DistributionModel):
    """Short-window frequency (baseline)."""

    name = "recent_frequency"

    def predict(self, X: np.ndarray) -> np.ndarray:
        return normalize_distribution(col(X, "freq_30"))


class EWFrequencyModel(DistributionModel):
    """Exponentially-weighted frequency — recent draws count more."""

    name = "ew_frequency"

    def __init__(self, temperature: float = 1.0):
        self.temperature = max(0.05, float(temperature))

    def predict(self, X: np.ndarray) -> np.ndarray:
        base = col(X, "ewf")
        p = normalize_distribution(base)
        if not np.isclose(self.temperature, 1.0):
            p = normalize_distribution(np.power(p + 1e-12, 1.0 / self.temperature))
        return p


class MarkovModel(DistributionModel):
    """First-order Markov transition model P(next | previous number),
    Laplace-smoothed (see builder: trans matrices with alpha prior)."""

    name = "markov"

    def __init__(self, blend_digits: float = 0.35):
        self.blend_digits = blend_digits  # weight of digit-level transitions

    def predict(self, X: np.ndarray) -> np.ndarray:
        p_num = col(X, "markov_number")            # already a distribution
        p_tens = col(X, "markov_tens")             # per-candidate tens prob
        p_ones = col(X, "markov_ones")             # per-candidate ones prob
        digit_prod = normalize_distribution(p_tens * p_ones)
        w = float(np.clip(self.blend_digits, 0.0, 1.0))
        return normalize_distribution((1 - w) * p_num + w * digit_prod)


class DigitModel(DistributionModel):
    """Independence model from tens/ones marginals of the transition stats."""

    name = "digit_model"

    def predict(self, X: np.ndarray) -> np.ndarray:
        p_tens = col(X, "markov_tens")
        p_ones = col(X, "markov_ones")
        return normalize_distribution(p_tens * p_ones)


class SetFeatureModel(DistributionModel):
    """SET-derived weak signal: kernel around the fractional digits of the
    most recent SET observation + mild pull toward recent SET direction.

    IMPORTANT: this is NOT the folk formula "SET decimals = result". The
    relationship is estimated from historical co-occurrence and only earns
    ensemble weight when walk-forward validation shows value.
    """

    name = "set_features"
    DEFAULT_WEIGHT = 0.15  # small prior weight; ensemble re-weights anyway

    def fit(self, X: np.ndarray, y: np.ndarray, groups: np.ndarray) -> None:
        # Estimate empirical lift of exact fractional-digit match on training data.
        try:
            n_groups = groups.max() + 1 if len(groups) else 0
            hits = 0
            total = 0
            for g in range(n_groups):
                mask = groups == g
                Xg = X[mask]
                yg = y[mask]
                match_col = Xg[:, self._match_idx]
                j = int(np.argmax(match_col))
                hits += int(yg[j])
                total += 1
            # Empirical P(hit | match) vs baseline 1/100.
            if total > 50 and hits > 0:
                lift = (hits / total) * N_NUMBERS
                self.weight = float(np.clip(self.DEFAULT_WEIGHT * min(lift, 3.0), 0.0, 0.45))
        except Exception:
            self.weight = self.DEFAULT_WEIGHT

    def __init__(self, feature_index: dict | None = None):
        from .feature_index import FEATURE_INDEX as IDX

        self._match_idx = (feature_index or IDX)["matches_set_frac_digits"]
        self._dist_idx = (feature_index or IDX)["dist_to_set_frac_digits"]
        self.weight = self.DEFAULT_WEIGHT

    def predict(self, X: np.ndarray) -> np.ndarray:
        dist = col(X, "dist_to_set_frac_digits")
        kernel = np.exp(-dist * 8.0)          # smooth proximity kernel
        base = np.full(N_NUMBERS, 1.0 / N_NUMBERS)
        signal = normalize_distribution(kernel)
        w = self.weight
        return normalize_distribution((1 - w) * base + w * signal)


ALL_STATISTICAL_MODELS = [
    UniformModel,
    FrequencyModel,
    RecentFrequencyModel,
    EWFrequencyModel,
    MarkovModel,
    DigitModel,
    SetFeatureModel,
]
