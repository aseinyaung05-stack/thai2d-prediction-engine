"""End-to-end engine test with the explicit MOCK repository (no DB)."""
import numpy as np
import pytest

from prediction import engine
from prediction.timeutils import yangon_today


@pytest.fixture(scope="module")
def prediction_payload(mock_repo):
    return engine.generate_prediction(
        "MORNING",
        session_date=yangon_today(),
        repository=mock_repo,
        persist=False,   # no DB in tests
    )


def test_prediction_structure(prediction_payload):
    p = prediction_payload
    assert "error" not in p or p.get("tier") != "TIER_1"
    assert len(p["_scores"]) == 100
    assert [s["rank"] for s in p["_scores"]] == list(range(1, 101))
    probs = np.array([s["calibrated_probability"] for s in p["_scores"]])
    assert abs(probs.sum() - 1.0) < 1e-4  # calibrated probabilities sum to ~100%


def test_sections_sum_to_total_probability(prediction_payload):
    p = prediction_payload
    total = sum(s["probability"] for s in p["section_scores"])
    assert abs(total - 1.0) < 1e-3
    for s in p["section_scores"]:
        assert s["candidate_count"] == 25
        assert 0 <= s["probability"] <= 1


def test_headline_wording_never_claims_guarantees(prediction_payload):
    view = prediction_payload["view"]
    text = json.dumps(view).lower()
    for banned in ("guaranteed win", "sure win", "100% sure", "certain win"):
        assert banned not in text
    assert "not a guaranteed section" in text


def test_tier_notices_present(prediction_payload):
    tier = prediction_payload["tier"]
    notice = prediction_payload["view"]["tier_notice"]
    if tier == "TIER_2":
        assert "ML Ensemble disabled" in notice
    elif tier == "TIER_1":
        assert "Insufficient" in notice


def test_top10_confidence_tiers(prediction_payload):
    tiers = [t["confidence_tier"] for t in prediction_payload["top10"]]
    assert tiers[0] == "HIGHER MODEL SUPPORT"
    assert all(t == "MODERATE MODEL SUPPORT" for t in tiers[3:10])


def test_edge_notice_when_no_statistical_advantage(mock_repo):
    """With near-uniform synthetic data the engine must NOT manufacture confidence."""
    payload = engine.generate_prediction(
        "AFTERNOON",
        session_date=yangon_today(),
        repository=mock_repo,
        persist=False,
    )
    # Either a real edge was measured, or the mandatory notice is shown.
    assert payload["edge"] is True or (
        payload["notice"] and "does not demonstrate a reliable predictive edge" in payload["notice"]
    )


import json  # noqa: E402
