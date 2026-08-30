"""Data quality scoring, tier gating and duplicate detection."""
import numpy as np
import pytest

from prediction.data.quality import compute_quality, data_tier, quality_gate
from tests.conftest import make_history


def test_quality_score_healthy_data():
    """Synthetic data ends on a Friday (weekends have no draws), so up to ~60h
    staleness is EXPECTED and correct — the score must still be solid, with
    zero true duplicates (date+session+number) and zero future timestamps."""
    df = make_history(n_days=200)
    rep = compute_quality(df)
    assert rep.score >= 65
    assert rep.duplicate_count == 0
    assert rep.future_timestamps == 0
    assert not any("duplicate" in w.lower() for w in rep.warnings)
    # Cross-session repeats are legitimate and must NOT be flagged:
    assert df.duplicated(subset=["date", "session", "number"]).sum() == 0


def test_duplicate_detection():
    """A true duplicate (same date+session, identical result) must be flagged."""
    df = make_history(n_days=120)
    dup_row = df.iloc[-1].copy()
    import pandas as pd

    df = pd.concat([df, pd.DataFrame([dup_row])], ignore_index=True)
    rep = compute_quality(df)
    assert rep.duplicate_count >= 1
    assert any("duplicate" in w.lower() for w in rep.warnings)


def test_cross_session_repeats_not_flagged():
    """Same number in MORNING and AFTERNOON of one day is normal data."""
    df = make_history(n_days=120)
    # Force every afternoon draw to equal that day's morning draw.
    for d in df["date"].unique():
        mask_m = (df["date"] == d) & (df["session"] == "MORNING")
        mask_a = (df["date"] == d) & (df["session"] == "AFTERNOON")
        if mask_m.any() and mask_a.any():
            df.loc[mask_a, "number"] = int(df.loc[mask_m, "number"].iloc[0])
            df.loc[mask_a, "tens"] = df.loc[mask_a, "number"] // 10
            df.loc[mask_a, "ones"] = df.loc[mask_a, "number"] % 10
    rep = compute_quality(df)
    assert rep.duplicate_count == 0


def test_stale_data_lowers_score(history_df):
    fresh = make_history(n_days=100)
    stale = fresh.copy()
    stale["ts"] = stale["ts"] - np.timedelta64(30, "D")  # everything 30 days old
    q_fresh = compute_quality(fresh).score
    q_stale = compute_quality(stale).score
    assert q_stale < q_fresh


def test_tiers_match_cold_start_spec():
    assert data_tier(50) == "TIER_1"
    assert data_tier(150) == "TIER_2"
    assert data_tier(600) == "TIER_3"
    assert data_tier(2000) == "TIER_4"


def test_quality_gate_blocks_tier1(mock_repo):
    from prediction.timeutils import session_cutoff_utc, yangon_today

    cutoff = session_cutoff_utc(yangon_today(), "MORNING")
    tiny = mock_repo(cutoff).iloc[:50]
    ok, reasons = quality_gate(tiny.reset_index(drop=True))
    assert not ok
    assert any("minimum" in r for r in reasons)


def test_ml_disabled_below_tier3():
    """Roster gating: TIER_2 gets no ML models."""
    from prediction.models.mlmodels import make_ml_models

    assert len(make_ml_models("TIER_2")) == 0
    assert len(make_ml_models("TIER_3")) >= 2


def test_ml_pipeline_smoke():
    """ML plumbing works on the pairwise dataset (fast logistic model)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    from prediction.models.mlmodels import SklearnPairwiseModel

    rng = np.random.default_rng(11)
    n_groups = 60
    X = rng.normal(size=(n_groups * 100, 6))
    winners = rng.integers(0, 100, n_groups)
    y = np.zeros(n_groups * 100)
    for g in range(n_groups):
        y[g * 100 + winners[g]] = 1.0
    model = SklearnPairwiseModel(
        "lr_test",
        Pipeline([("s", StandardScaler()), ("c", LogisticRegression(max_iter=300))]),
    )
    model.fit(X, y, None)
    p = model.predict(X[:100])
    assert abs(p.sum() - 1.0) < 1e-9
