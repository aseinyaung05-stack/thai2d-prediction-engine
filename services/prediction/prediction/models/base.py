"""Distribution model interface.

Every model consumes one causally-built Snapshot and outputs a score/probability
vector P(00)..P(99). Models NEVER see the target they are predicting.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

N_NUMBERS = 100


class DistributionModel(ABC):
    name: str = "base"

    def fit(self, X: np.ndarray, y: np.ndarray, groups: np.ndarray) -> None:
        """Optional supervised fitting on stacked (n*100, F) pairwise data."""

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return a length-100 vector for one candidate matrix (100, F)."""

    def predict_many(self, X_list: list[np.ndarray]) -> list[np.ndarray]:
        return [normalize_distribution(self.predict(X)) for X in X_list]


def normalize_distribution(p: np.ndarray) -> np.ndarray:
    """Normalize positive scores into a probability vector summing to ~1."""
    p = np.asarray(p, dtype=float)
    p = np.clip(p, 0, None)
    s = p.sum()
    if not np.isfinite(s) or s <= 0:
        return np.full(len(p), 1.0 / len(p))
    out = p / s
    # Numerical exactness for downstream log-loss computations.
    return out / out.sum()


def col(X: np.ndarray, name: str) -> np.ndarray:
    idx = FEATURE_INDEX.get(name)
    if idx is None:
        raise KeyError(f"Unknown feature column: {name}")
    return X[:, idx]


from .feature_index import FEATURE_INDEX  # noqa: E402  (single source of truth)
