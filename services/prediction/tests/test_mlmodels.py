"""ML model roster + training-boundary verification (STEP 9/10)."""
import numpy as np
import pytest

from prediction.models.base import DistributionModel, normalize_distribution
from prediction.models.mlmodels import (
    SklearnPairwiseModel,
    make_gradient_boosting_model,
    make_logistic_model,
    make_ml_models,
    try_make_xgboost,
)


def test_tier1_tier2_have_no_ml():
    assert make_ml_models("TIER_1") == []
    assert make_ml_models("TIER_2") == []


def test_tier3_enables_lr_and_gbm():
    names = [m.name for m in make_ml_models("TIER_3")]
    assert "logistic_regression" in names and "gradient_boosting" in names
    assert "random_forest" not in names


def test_tier4_adds_random_forest():
    names = [m.name for m in make_ml_models("TIER_4")]
    assert "random_forest" in names


def test_xgboost_optional_and_never_required():
    """XGBoost is OPTIONAL: absent lib -> None (system still works)."""
    m = try_make_xgboost()
    if m is not None:
        assert m.name == "xgboost"


def _pairwise_dataset(n_groups=40, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n_groups * 100, 6))
    winners = rng.integers(0, 100, n_groups)
    y = np.zeros(n_groups * 100)
    for g in range(n_groups):
        y[g * 100 + winners[g]] = 1.0
    return X, y


def test_sklearn_pairwise_model_outputs_distribution():
    X, y = _pairwise_dataset()
    model = make_logistic_model()
    model.fit(X, y, None)
    p = model.predict(X[:100])
    assert abs(p.sum() - 1.0) < 1e-9
    assert p.min() >= 0


def test_standardization_fitted_on_training_rows_only():
    """STEP 11: the StandardScaler inside the LR pipeline must see TRAIN data.

    We fit on a train slice whose known mean we compute ourselves and assert
    the scaler's stored mean_ equals it — i.e. no test rows leaked into
    preprocessing statistics.
    """
    X_train, y_train = _pairwise_dataset(n_groups=30, seed=1)

    est = make_logistic_model()
    est.fit(X_train, y_train, None)
    scaler = est.estimator.named_steps["scale"]
    expected_mean = X_train.mean(axis=0)
    assert np.allclose(scaler.mean_, expected_mean, atol=1e-8), (
        "Scaler statistics differ from train-only statistics — leakage!"
    )
    # And they must NOT equal full-data-with-future statistics:
    X_future, y_future = _pairwise_dataset(n_groups=10, seed=99)
    X_all = np.vstack([X_train, X_future])
    assert not np.allclose(scaler.mean_, X_all.mean(axis=0), atol=1e-8)


def test_fit_rejects_single_class_data():
    X, _ = _pairwise_dataset()
    y = np.zeros(len(X))
    with pytest.raises(ValueError):
        make_gradient_boosting_model().fit(X[:200], y[:200], None)


def test_predict_many_normalizes_each_snapshot(history_df):
    from prediction.features.builder import CausalFeatureBuilder

    snaps = CausalFeatureBuilder(min_history=60).build_snapshots(
        history_df.iloc[:150], session="MORNING"
    )
    model = UniformModel()
    outs = model.predict_many([s.X for s in snaps[:5]])
    for p in outs:
        assert abs(p.sum() - 1.0) < 1e-9


class UniformModel(DistributionModel):
    name = "uniform"

    def predict(self, X):
        return normalize_distribution(np.ones(X.shape[0]))
