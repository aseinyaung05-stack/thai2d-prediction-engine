"""ML models over the pairwise candidate dataset.

Each historical step contributes 100 rows (one per candidate number) with a
binary winner label. Classifiers are trained ONLY on training-fold rows and
produce per-candidate probabilities normalized within each snapshot group.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import (
    GradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .base import DistributionModel, normalize_distribution


class SklearnPairwiseModel(DistributionModel):
    """Common plumbing for sklearn classifiers on the pairwise dataset."""

    # ML models consume the SELECTED-feature subset chosen on training folds.
    needs_feature_selection = True

    def __init__(self, name: str, estimator, max_train_rows: int = 400_000):
        self.name = name
        self.estimator = estimator
        self.max_train_rows = max_train_rows

    def fit(self, X: np.ndarray, y: np.ndarray, groups: np.ndarray) -> None:
        if len(np.unique(y)) < 2:
            raise ValueError("Need both positive and negative samples to train.")
        if X.shape[0] > self.max_train_rows:
            idx = np.random.default_rng(42).choice(X.shape[0], self.max_train_rows, replace=False)
            X, y = X[idx], y[idx]
        self.estimator.fit(X, y)

    def predict(self, X: np.ndarray) -> np.ndarray:
        proba = self.estimator.predict_proba(X)[:, 1]
        return normalize_distribution(proba)


def make_logistic_model() -> SklearnPairwiseModel:
    return SklearnPairwiseModel(
        "logistic_regression",
        Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "clf",
                    LogisticRegression(
                        C=0.1,
                        max_iter=1000,
                        class_weight="balanced",
                        random_state=42,
                    ),
                ),
            ]
        ),
    )


def make_random_forest_model() -> SklearnPairwiseModel:
    return SklearnPairwiseModel(
        "random_forest",
        RandomForestClassifier(
            n_estimators=200,
            min_samples_leaf=50,
            max_features="sqrt",
            n_jobs=-1,
            random_state=42,
            class_weight="balanced_subsample",
        ),
        max_train_rows=150_000,
    )


def make_gradient_boosting_model() -> SklearnPairwiseModel:
    return SklearnPairwiseModel(
        "gradient_boosting",
        GradientBoostingClassifier(
            n_estimators=150,
            learning_rate=0.05,
            max_depth=3,
            subsample=0.8,
            random_state=42,
        ),
        max_train_rows=120_000,
    )


def make_ml_models(tier: str):
    """Cold-start aware ML roster (spec: TIER gating).

    TIER_1/2: no ML (caller also gates). TIER_3: LR + GBM.
    TIER_4: adds Random Forest for advanced comparison.
    """
    if tier not in ("TIER_3", "TIER_4"):
        return []
    models = [make_logistic_model(), make_gradient_boosting_model()]
    if tier == "TIER_4":
        models.append(make_random_forest_model())
    return models


# Optional advanced gradient libraries are only adopted when walk-forward
# validation shows genuine improvement (spec: OPTIONAL ADVANCED MODEL).
def try_make_xgboost():
    try:
        from xgboost import XGBClassifier  # type: ignore

        return SklearnPairwiseModel(
            "xgboost",
            XGBClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                eval_metric="logloss",
                random_state=42,
                verbosity=0,
            ),
            max_train_rows=120_000,
        )
    except ImportError:
        return None
