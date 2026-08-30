"""Chronological walk-forward evaluation.

NEVER shuffles time-series data. Splits: first 60% train, next 20%
validation (used for ensemble weighting, calibration, model selection),
final 20% test — touched exactly once at the end.

For every evaluated prediction point, features were generated strictly from
earlier observations by CausalFeatureBuilder, so no future leakage exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from ..config import settings
from ..features.builder import CausalFeatureBuilder, Snapshot, section_of_array
from ..features.selection import select_features
from ..models.base import DistributionModel, normalize_distribution
from ..models.baselines import (
    DigitModel,
    EWFrequencyModel,
    FrequencyModel,
    MarkovModel,
    RecentFrequencyModel,
    SetFeatureModel,
    UniformModel,
)
from ..models.ensemble import EnsembleModel, TemperatureScaler, _mix_loglinear
from ..models.mlmodels import make_ml_models, try_make_xgboost
from . import metrics as M
from .significance import compare_topk_to_baseline


@dataclass
class WalkForwardResult:
    split_info: dict
    model_metrics: dict = field(default_factory=dict)
    segment_performance: dict = field(default_factory=dict)
    rolling_performance: dict = field(default_factory=dict)
    significance: dict = field(default_factory=dict)
    selected_features: list = field(default_factory=list)
    feature_selection_meta: dict = field(default_factory=dict)
    production_model: str = ""
    edge_detected: bool = False
    component_val_preds: dict = field(default_factory=dict)
    y_test: np.ndarray | None = None
    ts_test: list = field(default_factory=list)
    ensemble_weights: dict = field(default_factory=dict)
    calibration_temperature: float = 1.0


def _stack(snapshots: list[Snapshot]):
    X_list = [s.X for s in snapshots]
    y = np.array([s.target if s.target is not None else -1 for s in snapshots])
    groups = np.repeat(np.arange(len(snapshots)), 100)
    X = np.vstack(X_list)
    return X, y, groups


def run_walk_forward(
    df,
    session: str,
    halflife: int = 30,
    max_steps: int | None = None,
    include_ml: bool = True,
    verbose: bool = False,
) -> WalkForwardResult:
    """Evaluate all models chronologically and select the production model."""
    max_steps = max_steps or settings.max_walkforward_steps
    builder = CausalFeatureBuilder(halflife=halflife, min_history=60, max_snapshots=max_steps)
    snapshots = builder.build_snapshots(df, session=session)
    if len(snapshots) < 50:
        raise ValueError(
            f"Insufficient history for walk-forward evaluation ({len(snapshots)} points)."
        )

    n = len(snapshots)
    n_train = int(n * settings.wf_train_fraction)
    n_val = int(n * settings.wf_validation_fraction)
    tr_idx = np.arange(0, n_train)
    va_idx = np.arange(n_train, n_train + n_val)
    te_idx = np.arange(n_train + n_val, n)

    X_all, y_all, _groups = _stack(snapshots)

    # ---- feature selection fitted ONLY on the training portion -------------
    sel_idx, feat_meta = select_features(
        X_all[tr_idx * 100], y_all[tr_idx], settings.feature_correlation_threshold
    )

    def rows(idxs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Flat pairwise rows + labels for the given snapshot indices."""
        r = np.concatenate([np.arange(i * 100, i * 100 + 100) for i in idxs])
        y_flat = np.repeat(y_all[idxs], 100)  # label is per-SNAPSHOT, repeated per candidate
        return X_all[r], y_flat

    # ---- candidate roster ---------------------------------------------------
    statistical: list[DistributionModel] = [
        UniformModel(),
        FrequencyModel(),
        RecentFrequencyModel(),
        EWFrequencyModel(),
        MarkovModel(),
        DigitModel(),
        SetFeatureModel(feature_index={n: i for i, n in enumerate(snapshots[0].feature_names)}),
    ]
    ml_models = []
    tier_rows = n_train * 2  # two draws/day approximation of record depth
    if include_ml and tier_rows >= settings.tier3_min:
        ml_models.extend(make_ml_models("TIER_3" if tier_rows < settings.tier4_min else "TIER_4"))
        xgb = try_make_xgboost()
        if xgb is not None:
            ml_models.append(xgb)

    Xtr_flat, ytr_flat = rows(tr_idx)

    # ---- fit ML components on TRAIN ONLY ------------------------------------
    for m in ml_models:
        Xm = Xtr_flat[:, sel_idx]
        try:
            m.fit(Xm, ytr_flat, None)
            if verbose:
                print(f"  fitted {m.name}")
        except ValueError as e:
            print(f"  skipping {m.name}: {e}")
            m.disabled = True  # type: ignore[attr-defined]
    ml_models = [m for m in ml_models if not getattr(m, "disabled", False)]

    all_components = statistical + ml_models

    # ---- generate distributions for every snapshot ---------------------------
    from ..models.ensemble import model_input

    def predict_all(models, idxs: np.ndarray) -> dict[str, np.ndarray]:
        out: dict[str, list[np.ndarray]] = {}
        for name in [m.name for m in models]:
            out[name] = []
        for t in idxs:
            snap = snapshots[t]
            for m in models:
                Xin = model_input(m, snap.X, sel_idx)
                out[m.name].append(normalize_distribution(m.predict(Xin)))
        return {k: np.asarray(v) for k, v in out.items()}

    val_preds = predict_all(all_components, va_idx)
    test_preds = predict_all(all_components, te_idx)

    y_va = y_all[va_idx]
    y_te = y_all[te_idx]

    # ---- ensemble weight optimization on VALIDATION ONLY ---------------------
    ens = EnsembleModel(components=all_components)
    comp_stack = np.stack([val_preds[m.name] for m in all_components], axis=1)
    ens.fit_weights(comp_stack, y_va)
    val_preds["ensemble"] = normalize_distribution(
        _mix_loglinear(ens.weights, comp_stack)
    )
    test_comp_stack = np.stack([test_preds[m.name] for m in all_components], axis=1)
    test_preds["ensemble"] = normalize_distribution(
        _mix_loglinear(ens.weights, test_comp_stack)
    )

    # ---- temperature calibration fitted on VALIDATION ONLY -------------------
    scaler = TemperatureScaler()
    raw_prod_val = val_preds[ens.name]
    scaler.fit(raw_prod_val, y_va)

    result = WalkForwardResult(
        split_info={
            "train_points": int(len(tr_idx)),
            "validation_points": int(len(va_idx)),
            "test_points": int(len(te_idx)),
            "train_start": str(snapshots[0].date),
            "train_end": str(snapshots[n_train - 1].date),
            "validation_end": str(snapshots[n_train + n_val - 1].date),
            "test_end": str(snapshots[-1].date),
            "session": session,
            "halflife": halflife,
        },
        selected_features=[snapshots[0].feature_names[i] for i in sel_idx],
        feature_selection_meta=feat_meta,
    )

    # ---- final test evaluation ------------------------------------------------
    # NOTE: validation metrics MUST come from val_preds (validation period).
    # Computing them from `test_preds` here was a leakage bug: validation
    # scores would silently depend on test-period predictions.
    for name, preds in test_preds.items():
        calibrated = (
            np.vstack([scaler.transform(p) for p in preds]) if name == ens.name else preds
        )
        result.model_metrics[name] = M.evaluate_all(calibrated, y_te)
        val_p = val_preds[name]
        result.component_val_preds[name] = {
            "val_log_loss": round(M.log_loss(val_p, y_va), 6),
            "val_top10_hit_rate": round(M.topk_hit(val_p, y_va, 10), 5),
        }

    # Production selection uses VALIDATION ONLY (never test accuracy):
    candidates = {k: v["val_log_loss"] for k, v in result.component_val_preds.items()}
    baseline_names = ["uniform", "frequency", "recent_frequency", "ew_frequency"]
    production, edge = select_production_model(candidates, baseline_names)
    result.production_model = production
    result.edge_detected = bool(edge)
    if not edge:
        result.significance["notice"] = (
            "No reliable predictive edge detected in current historical data."
        )

    # Significance of chosen model's top-10 vs uniform-random expectation.
    prod_hits = np.array(
        [int(y_te[i] in np.argsort(test_preds[result.production_model][i])[::-1][:10]) for i in range(len(y_te))]
    )
    uni_hits = (np.random.default_rng(7).random(len(y_te)) < 0.10).astype(int)
    result.significance["top10_vs_uniform"] = compare_topk_to_baseline(
        prod_hits.astype(float), uni_hits.astype(float), 0.10
    )

    # ---- segmented + rolling performance for production model -----------------
    prod_test = test_preds[result.production_model]
    sess = np.array([snapshots[t].session for t in te_idx])
    months = np.array([str(snapshots[t].date)[:7] for t in te_idx])
    years = np.array([str(snapshots[t].date)[:4] for t in te_idx])
    result.segment_performance = {
        "by_session": M.evaluate_by_segment(prod_test, y_te, sess),
        "by_month": M.evaluate_by_segment(prod_test, y_te, months),
        "by_year": M.evaluate_by_segment(prod_test, y_te, years),
    }
    result.rolling_performance = {
        "rolling_top10_last30": float(prod_hits[-30:].mean()) if len(prod_hits) >= 30 else None,
        "rolling_top10_last100": float(prod_hits[-100:].mean()) if len(prod_hits) >= 100 else None,
    }
    result.y_test = y_te
    result.ts_test = [str(snapshots[t].ts) for t in te_idx]
    # Auditability / leakage-proofing artifacts (STEP 11 verification hooks):
    result.ensemble_weights = {m.name: float(w) for m, w in zip(all_components, ens.weights)}
    result.calibration_temperature = float(scaler.temperature)
    result.split_info.update(
        {
            "train_last_snapshot_index": int(tr_idx[-1]),
            "validation_first_index": int(va_idx[0]),
            "test_first_index": int(te_idx[0]),
            # df-row positions (snapshot indices differ after subsampling):
            "train_last_df_position": int(snapshots[tr_idx[-1]].index),
            "validation_first_df_position": int(snapshots[va_idx[0]].index),
            "test_first_df_position": int(snapshots[te_idx[0]].index),
            "train_last_ts": str(snapshots[tr_idx[-1]].ts),
            "first_evaluated_ts": str(snapshots[va_idx[0]].ts),
        }
    )
    return result


def select_production_model(
    val_log_losses: dict[str, float], baseline_names: list[str], min_margin: float = 1e-9
) -> tuple[str, bool]:
    """Pure selection rule (unit-testable, spec: BASELINE-FIRST + MODEL SELECTION).

    An advanced model becomes production ONLY if its validation log loss beats
    EVERY baseline. Data volume alone never grants production status — the
    caller gates ML eligibility by tier; this function gates by performance.
    Returns (production_model_name, edge_detected).
    """
    baselines = {k: v for k, v in val_log_losses.items() if k in baseline_names}
    advanced = {k: v for k, v in val_log_losses.items() if k not in baseline_names}
    best_baseline = min(baselines.values()) if baselines else float("inf")
    if advanced:
        best_adv_name = min(advanced, key=advanced.get)
        if advanced[best_adv_name] < best_baseline - min_margin:
            return best_adv_name, True
    # Fallback: strongest baseline by validation loss.
    fallback = min(baselines, key=baselines.get)
    return (fallback or "uniform"), False

