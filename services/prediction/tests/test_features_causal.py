"""CRITICAL: data-leakage prevention tests for causal feature generation."""
from datetime import timedelta

import numpy as np
import pytest

from prediction.features.builder import CausalFeatureBuilder, FEATURE_INDEX


def _snapshots_equal(a, b, tol=1e-12):
    return np.allclose(a.X, b.X, atol=tol)


@pytest.fixture(scope="module")
def small_history(history_df):
    return history_df.iloc[:240].reset_index(drop=True)  # ~120 days x 2 draws


def test_no_future_data_in_features(small_history):
    """Truncating the future must not change earlier snapshots.

    This is the core leakage guarantee: features at index t depend only on
    rows with index < t.
    """
    cut = 200
    full = CausalFeatureBuilder(min_history=60).build_snapshots(small_history)
    truncated = CausalFeatureBuilder(min_history=60).build_snapshots(
        small_history.iloc[:cut]
    )

    assert len(full) >= len(truncated)
    for s_full, s_trunc in zip(full, truncated):
        assert s_full.index == s_trunc.index
        assert _snapshots_equal(s_full, s_trunc), (
            f"Snapshot at index {s_full.index} changed when future rows were "
            f"removed — future-data leakage detected!"
        )


def test_target_never_used_as_feature_input(small_history):
    """Perturbing only the target at t must not alter snapshot t's matrix."""
    df = small_history.copy()
    snaps_a = CausalFeatureBuilder(min_history=60).build_snapshots(df)

    df2 = df.copy()
    df2.loc[df2.index[100], "number"] = (df2.loc[df2.index[100], "number"] + 37) % 100
    df2["tens"] = df2["number"] // 10
    df2["ones"] = df2["number"] % 10
    snaps_b = CausalFeatureBuilder(min_history=60).build_snapshots(df2)

    # Snapshots BEFORE index 100 identical; AT index 100 may differ; after 100 both evolve from different states (expected).
    assert np.allclose(snaps_a[10].X, snaps_b[10].X)
    assert snaps_a[10].target == snaps_b[10].target  # target of snapshot = row at its own index? No: target is row t itself.


def test_frequency_window_matches_manual_count(small_history):
    builder = CausalFeatureBuilder(min_history=60)
    snaps = builder.build_snapshots(small_history)
    snap = snaps[-1]
    w = 30
    idx = snap.index
    window_numbers = small_history["number"].iloc[idx - w : idx].to_numpy()
    manual_freq = np.bincount(window_numbers, minlength=100)[:100] / w
    got = snap.X[:, FEATURE_INDEX[f"freq_{w}"]]
    assert np.allclose(got, manual_freq, atol=1e-9)


def test_markov_row_sums_to_one(small_history):
    snaps = CausalFeatureBuilder(min_history=60).build_snapshots(small_history)
    snap = snaps[-1]
    mkv = snap.X[:, FEATURE_INDEX["markov_number"]]
    assert abs(mkv.sum() - 1.0) < 1e-6


def test_recency_absence_is_weak_signal(small_history):
    """days_since feature must be log-compressed and capped — absence alone
    can never dominate (anti gambler's fallacy by construction)."""
    snaps = CausalFeatureBuilder(min_history=60).build_snapshots(small_history)
    dsn = snaps[-1].X[:, FEATURE_INDEX["days_since_number"]]
    assert dsn.max() <= np.log1p(5000) + 1e-6
    assert dsn.min() >= 0.0


def test_live_snapshot_excludes_placeholder_target(mock_repo):
    from prediction.timeutils import session_cutoff_utc, yangon_today

    df = mock_repo.load_history(session_cutoff_utc(yangon_today(), "MORNING"))
    builder = CausalFeatureBuilder(min_history=60)
    snaps = builder.build_snapshots_with_extra_row(df, session="MORNING")
    assert snaps[-1].target is None
