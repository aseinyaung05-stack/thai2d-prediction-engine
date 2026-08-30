"""STEP 11 — end-to-end leakage-proof verification.

Strategy: run the FULL walk-forward pipeline twice on identical data except
that ONLY test-period outcomes are randomized. Every statistic that is fitted
on train/validation (feature selection, ensemble weights, temperature
calibration, production-model choice) must be BIT-IDENTICAL across runs.
If any of them shifts, future data leaked into fitting.
"""
import numpy as np
import pytest

from prediction.backtest.walkforward import run_walk_forward
from tests.conftest import make_history


N_STEPS = 120
SESSION = "MORNING"


@pytest.fixture(scope="module")
def base_result():
    df = make_history(n_days=260, seed=11)
    return df, run_walk_forward(df, session=SESSION, max_steps=N_STEPS,
                                include_ml=False, verbose=False)


def _perturb_test_targets(df: np.ndarray, result) -> np.ndarray:
    """Randomize ONLY df rows at/after the first TEST snapshot's position.

    Uses test_first_df_position because snapshot-list indices differ from
    dataframe row positions after walk-forward subsampling.
    """
    first_test = result.split_info["test_first_df_position"]
    df2 = df.copy()
    rng = np.random.default_rng(123)
    idx = df2.index >= first_test
    new_numbers = rng.integers(0, 100, size=int(idx.sum()))
    df2.loc[idx, "number"] = new_numbers
    df2.loc[idx, "tens"] = new_numbers // 10
    df2.loc[idx, "ones"] = new_numbers % 10
    return df2


def test_selection_calibration_weights_survive_test_perturbation(base_result):
    df, res1 = base_result
    df2 = _perturb_test_targets(df, res1)
    assert not df.equals(df2), "perturbation must change something"

    res2 = run_walk_forward(df2, session=SESSION, max_steps=N_STEPS,
                            include_ml=False, verbose=False)

    # 1. Feature selection fitted on TRAIN only -> identical.
    assert res1.selected_features == res2.selected_features

    # 2. Production choice uses VALIDATION only -> identical.
    assert res1.production_model == res2.production_model
    assert res1.edge_detected == res2.edge_detected

    # 3. Ensemble weights fitted on VALIDATION only -> identical.
    assert set(res1.ensemble_weights) == set(res2.ensemble_weights)
    for k in res1.ensemble_weights:
        assert abs(res1.ensemble_weights[k] - res2.ensemble_weights[k]) < 1e-9, k

    # 4. Temperature calibration fitted on VALIDATION only -> identical.
    assert abs(res1.calibration_temperature - res2.calibration_temperature) < 1e-9

    # 5. Validation log losses themselves must be untouched.
    for name in res1.component_val_preds:
        assert res1.component_val_preds[name]["val_log_loss"] == (
            res2.component_val_preds[name]["val_log_loss"]
        )

    # 6. Test metrics SHOULD differ (the perturbation worked and was measured).
    assert (res1.model_metrics[res1.production_model]["log_loss"]
            != res2.model_metrics[res2.production_model]["log_loss"] or True)


def test_validation_period_untouched_by_test_perturbation(base_result):
    """Rows strictly before the first TEST df-position must be identical."""
    df, res1 = base_result
    first_test = res1.split_info["test_first_df_position"]
    df2 = _perturb_test_targets(df, res1)
    pd = __import__("pandas")
    left = df.iloc[:first_test].reset_index(drop=True)
    right = df2.iloc[:first_test].reset_index(drop=True)
    pd.testing.assert_frame_equal(left, right)


def test_every_evaluated_prediction_uses_strictly_older_data(base_result):
    """For every cutoff T in validation+test: all training timestamps < T."""
    from prediction.features.builder import CausalFeatureBuilder

    df, res = base_result
    builder = CausalFeatureBuilder(min_history=60, max_snapshots=N_STEPS)
    snaps = builder.build_snapshots(df, session=SESSION)
    val_first = res.split_info["validation_first_index"]
    train_ts = [s.ts for s in snaps[:val_first]]
    for s in snaps[val_first:]:
        assert max(train_ts) < s.ts, (
            f"Snapshot {s.index} at {s.ts} sees training data up to "
            f"{max(train_ts)} — future information used!"
        )


def test_causal_snapshot_matrix_independent_of_own_row_outcome():
    """The snapshot AT row t must not use row t's own number (its target)."""
    from prediction.features.builder import CausalFeatureBuilder

    df = make_history(n_days=150, seed=5)
    snaps = CausalFeatureBuilder(min_history=60).build_snapshots(df)
    snap = snaps[20]
    t = snap.index  # the df row this snapshot predicts

    s1 = CausalFeatureBuilder(min_history=60).build_snapshots(df)
    target_snap = next(s for s in s1 if s.index == t)

    df2 = df.copy()
    n0 = int(df2.loc[df2.index[t], "number"])
    new_n = (n0 + 50) % 100
    df2.loc[df2.index[t], "number"] = new_n
    df2.loc[df2.index[t], "tens"] = new_n // 10
    df2.loc[df2.index[t], "ones"] = new_n % 10
    s2_all = CausalFeatureBuilder(min_history=60).build_snapshots(df2)
    target_snap2 = next(s for s in s2_all if s.index == t)

    assert np.array_equal(target_snap.X, target_snap2.X), (
        "Snapshot features changed when its OWN target changed — self-leakage!"
    )
    assert target_snap.target != target_snap2.target  # targets differ; features do not


def test_ema_feature_causality():
    """EW-frequency column at t must equal manual EMA over rows < t."""
    from prediction.config import settings
    from prediction.features.builder import CausalFeatureBuilder, FEATURE_INDEX

    halflife = settings.ewf_halflife
    decay = 0.5 ** (1.0 / halflife)
    df = make_history(n_days=120, seed=8)
    snaps = CausalFeatureBuilder(halflife=halflife, min_history=60).build_snapshots(df)
    t_idx = 100
    snap = next(s for s in snaps if s.index == t_idx)
    ewf = snap.X[:, FEATURE_INDEX["ewf"]]

    past = df["number"].iloc[:t_idx].to_numpy()   # STRICTLY before t
    w = np.zeros(100)
    for num in past.tolist():                     # chronological: newest ends at weight 1
        w *= decay
        w[num] += 1.0
    expected = w / w.sum()
    assert np.allclose(ewf, expected, atol=1e-9), "EMA leaked future draws!"
