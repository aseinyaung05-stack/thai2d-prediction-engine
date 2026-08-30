"""Per-session model separation (spec §11) — builder stream tests."""
import numpy as np

from prediction.features.builder import CausalFeatureBuilder, FEATURE_INDEX
from tests.conftest import make_history


def test_snapshots_only_target_requested_session():
    """With session='MORNING', every snapshot predicts a MORNING row."""
    df = make_history(n_days=120, seed=3)
    snaps = CausalFeatureBuilder(min_history=60).build_snapshots(df, session="MORNING")
    assert len(snaps) > 10
    for s in snaps:
        assert str(df.iloc[s.index]["session"]) == "MORNING"
        assert s.session == "MORNING"


def test_frequency_windows_contain_only_own_session():
    """freq windows must count ONLY the session's own draws."""
    df = make_history(n_days=120, seed=3)
    snaps = CausalFeatureBuilder(min_history=60).build_snapshots(df, session="MORNING")
    snap = snaps[-1]
    w = 30
    pos = snap.index
    morning_rows = df[(df["session"] == "MORNING") & (df.index < pos)]
    window_numbers = morning_rows["number"].iloc[-w:].to_numpy()
    manual = np.bincount(window_numbers, minlength=100)[:100] / w
    got = snap.X[:, FEATURE_INDEX["freq_30"]]
    assert np.allclose(got, manual, atol=1e-9)


def test_cross_session_feature_uses_other_session_draw():
    """same_tens_prev_session must reflect the OTHER session's last draw."""
    df = make_history(n_days=120, seed=3)
    snaps = CausalFeatureBuilder(min_history=60).build_snapshots(df, session="MORNING")
    snap = snaps[-1]
    pos = snap.index
    # most recent AFTERNOON draw strictly before this MORNING row
    prior_afternoon = df[(df["session"] == "AFTERNOON") & (df.index < pos)]
    assert len(prior_afternoon) > 0
    other_num = int(prior_afternoon.iloc[-1]["number"])
    assert snap.prev_cross_session_number == other_num
    otens, oones = divmod(other_num, 10)
    col = snap.X[:, FEATURE_INDEX["same_tens_prev_session"]]
    assert col[otens * 10 + oones] == 1.0  # candidate == other session's last draw


def test_morning_and_afternoon_distributions_differ():
    """The whole point: the two session models must not be identical."""
    df = make_history(
        n_days=160, seed=5,
        biased_session="MORNING", favorite_numbers=(7, 19, 33),
    )
    b = CausalFeatureBuilder(min_history=60)
    m = b.build_snapshots(df, session="MORNING")[-1]
    a = b.build_snapshots(df, session="AFTERNOON")[-1]
    from prediction.models.baselines import EWFrequencyModel

    pm = EWFrequencyModel().predict(m.X)
    pa = EWFrequencyModel().predict(a.X)
    assert not np.allclose(pm, pa), "session streams produced identical distributions"


def test_no_session_param_keeps_mixed_stream_backcompat():
    """session=None keeps the original interleaved behavior (backtests of
    the pooled stream still work; leakage tests rely on it)."""
    df = make_history(n_days=120, seed=3)
    snaps = CausalFeatureBuilder(min_history=60).build_snapshots(df)
    sessions_seen = {str(df.iloc[s.index]["session"]) for s in snaps}
    assert sessions_seen == {"MORNING", "AFTERNOON"}
