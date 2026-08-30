"""Probability normalization + calibration/ensemble guarantees."""
import numpy as np

from prediction.models.base import normalize_distribution
from prediction.models.baselines import (
    EWFrequencyModel,
    FrequencyModel,
    MarkovModel,
    SetFeatureModel,
    UniformModel,
)
from prediction.models.ensemble import EnsembleModel, TemperatureScaler


def test_normalize_sums_to_one():
    p = normalize_distribution(np.array([1.0, 2.0, 3.0]))
    assert abs(p.sum() - 1.0) < 1e-12


def test_normalize_handles_zeros_and_negatives():
    p = normalize_distribution(np.array([-5.0, 0.0, 10.0, 0.0]))
    assert p.min() >= 0
    assert abs(p.sum() - 1.0) < 1e-12
    assert p[2] > 0.99


def test_normalize_all_zero_returns_uniform():
    p = normalize_distribution(np.zeros(100))
    assert np.allclose(p, np.full(100, 0.01))


def test_statistical_models_output_valid_distributions(history_df):
    from prediction.features.builder import CausalFeatureBuilder

    snaps = CausalFeatureBuilder(min_history=60).build_snapshots(
        history_df.iloc[:200], session="MORNING"
    )
    snap = snaps[-1]
    for model in (UniformModel(), FrequencyModel(), EWFrequencyModel(),
                  MarkovModel(), SetFeatureModel()):
        p = model.predict(snap.X)
        assert len(p) == 100
        assert abs(p.sum() - 1.0) < 1e-9, model.name
        assert p.min() >= 0


def test_ensemble_weights_stay_on_simplex():
    rng = np.random.default_rng(3)
    G, C = 80, 3
    comp = rng.dirichlet(np.ones(100), size=(G, C))
    y = rng.integers(0, 100, G)
    ens = EnsembleModel(components=[UniformModel()] * C)
    w = ens.fit_weights(comp, y)
    assert abs(w.sum() - 1.0) < 1e-6
    assert w.min() >= 0


def test_ensemble_loglinear_mix_is_distribution():
    rng = np.random.default_rng(4)
    stack = rng.dirichlet(np.ones(100), size=(10, 2))
    from prediction.models.ensemble import _mix_loglinear

    mix = _mix_loglinear(np.array([0.6, 0.4]), stack)
    assert np.allclose(mix.sum(axis=1), 1.0, atol=1e-9)
    assert mix.min() >= 0


def test_temperature_scaling_preserves_normalization():
    rng = np.random.default_rng(5)
    preds = rng.dirichlet(np.ones(100), size=50)
    y = rng.integers(0, 100, 50)
    sc = TemperatureScaler()
    T = sc.fit(preds, y)
    assert 0.25 <= T <= 4.0
    out = sc.transform(preds[0])
    assert abs(out.sum() - 1.0) < 1e-9
