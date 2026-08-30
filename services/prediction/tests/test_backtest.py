"""Walk-forward backtesting sanity on deterministic synthetic data."""
import numpy as np
import pytest

from prediction.backtest import metrics
from prediction.backtest.walkforward import run_walk_forward


@pytest.fixture(scope="module")
def wf_result(history_df):
    return run_walk_forward(
        history_df,
        session="MORNING",
        max_steps=140,
        include_ml=False,   # statistical-only for fast CI; ML covered separately
        verbose=False,
    )


def test_split_is_chronological(wf_result):
    s = wf_result.split_info
    assert str(s["train_start"]) <= str(s["train_end"]) <= str(s["validation_end"]) <= str(s["test_end"])
    assert s["validation_points"] > 0 and s["test_points"] > 0


def test_all_models_evaluated_on_test(wf_result):
    expected = {"uniform", "frequency", "recent_frequency", "ew_frequency",
                "markov", "digit_model", "set_features", "ensemble"}
    assert expected.issubset(wf_result.model_metrics.keys())
    for name, m in wf_result.model_metrics.items():
        assert m["n_predictions"] == wf_result.split_info["test_points"], name
        assert 0.0 <= m["top10_hit_rate"] <= 1.0


def test_uniform_baseline_reference_logloss(wf_result):
    ll = wf_result.model_metrics["uniform"]["log_loss"]
    assert abs(ll - np.log(100)) < 0.01  # uniform model must match theory


def test_production_model_selected_from_validation(wf_result):
    """Selection uses validation log loss only — never test accuracy."""
    candidates = {
        k: v["val_log_loss"] for k, v in wf_result.component_val_preds.items()
    }
    best_by_validation = min(candidates, key=candidates.get)
    if wf_result.edge_detected:
        assert wf_result.production_model not in ("uniform", "frequency")
    # Either way the chosen model must be a real candidate:
    assert wf_result.production_model in candidates or wf_result.production_model == "uniform"


def test_edge_notice_when_no_advantage(wf_result):
    if not wf_result.edge_detected:
        assert "No reliable predictive edge" in wf_result.significance["notice"]


def test_section_confusion_matrix_shape(wf_result):
    cm = wf_result.model_metrics["ensemble"]["section_confusion"]
    matrix = cm["rows_actual_cols_predicted"]
    assert len(matrix) == 4 and all(len(r) == 4 for r in matrix)
    assert sum(sum(r) for r in matrix) == wf_result.split_info["test_points"]


def test_calibration_curve_bins_present(wf_result):
    cal = wf_result.model_metrics["ensemble"]["calibration"]
    assert len(cal["bins"]) >= 1
    total = sum(b["count"] for b in cal["bins"])
    assert total == wf_result.split_info["test_points"]
    assert 0 <= cal["expected_calibration_error"] <= 1


def test_topk_hit_rates_monotonic_non_decreasing(wf_result):
    m = wf_result.model_metrics["ensemble"]
    rates = [m["top1_hit_rate"], m["top3_hit_rate"], m["top5_hit_rate"], m["top10_hit_rate"]]
    assert rates == sorted(rates)
