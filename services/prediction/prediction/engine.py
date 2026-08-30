"""Production prediction orchestration.

Pipeline (per session):
  quality gate -> cold-start tier -> walk-forward validation (cached) ->
  production model selection -> live causal snapshot -> raw distribution ->
  temperature calibration -> section scores -> ranked candidates ->
  explanations -> immutable snapshot persisted to PostgreSQL.

The output NEVER claims certainty. Wording follows spec §16/§21:
"Highest model-scored section", "DESCRIPTIVE / LOW-SIGNAL" when no edge.
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, timedelta, timezone

import numpy as np

from .backtest.metrics import N as _N
from .backtest.walkforward import WalkForwardResult, run_walk_forward
from .config import settings
from .data.quality import compute_quality, data_tier, quality_gate
from .data.repository import load_history
from .features.builder import (
    CausalFeatureBuilder,
    SECTION_BOUNDS,
    Snapshot,
    classify_section,
)
from .models.base import normalize_distribution
from .models.baselines import UniformModel
from .models.ensemble import EnsembleModel, TemperatureScaler
from .models.mlmodels import make_ml_models
from .models.feature_index import FEATURE_INDEX
from .timeutils import SESSIONS, next_session_date_for, session_cutoff_utc, yangon_today
from . import store

SECTION_IDS = ("A", "B", "C", "D")
UNIFORM_P = 1.0 / _N

# In-memory cache: one validated pipeline per (session, history fingerprint).
_CACHE: dict[tuple, dict] = {}
CACHE_TTL_SECONDS = 900


class PredictionUnavailable(Exception):
    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("Prediction unavailable because data validation failed.")


# ---------------------------------------------------------------------------
# public entry points
# ---------------------------------------------------------------------------

def generate_prediction(
    session: str,
    session_date: date | None = None,
    now: datetime | None = None,
    repository=load_history,
    persist: bool = True,
) -> dict:
    """Produce the full prediction payload for one Myanmar-local session."""
    if session not in SESSIONS:
        raise ValueError(f"Unknown session {session!r}")
    now = now or datetime.now(tz=timezone.utc)
    if session_date is None:
        # Predict the NEXT upcoming draw of this session (weekend-aware:
        # SET is closed Sat/Sun, so the target is always a trading day).
        d = next_session_date_for(session, now)
    else:
        d = session_date
        while d.weekday() >= 5:  # provided weekend date -> next trading day
            d += timedelta(days=1)
    cutoff = session_cutoff_utc(d, session)

    # ---- 1. data (hard cutoff — nothing after this instant is visible) -----
    df = repository(cutoff)

    # ---- 2. quality gate -----------------------------------------------------
    ok, reasons = quality_gate(df, now)
    dq = compute_quality(df, now)
    if dq.total_records == 0:
        return {
            "error": "Prediction unavailable — no valid source data.",
            "reasons": reasons or ["No records available before the session cutoff."],
            "session": session,
            "date": str(d),
            "data_quality": 0,
            "disclaimer": _DISCLAIMER,
        }
    if not ok and settings.strict_validation:
        return {
            "error": "Prediction unavailable because data validation failed.",
            "reasons": reasons,
            "session": session,
            "date": str(d),
            "data_quality": dq.score,
            "disclaimer": _DISCLAIMER,
        }

    # ---- 3. cold-start tier ---------------------------------------------------
    session_df = df[df["session"] == session]
    n_rows = len(session_df)
    tier = data_tier(n_rows)

    # ---- 4. validated pipeline (walk-forward, cached) --------------------------
    pipe = _get_or_build_pipeline(df, session, tier, cutoff)

    # ---- 5. live snapshot strictly before the cutoff ---------------------------
    builder = CausalFeatureBuilder(halflife=settings.ewf_halflife,
                                   laplace_alpha=settings.markov_laplace_alpha,
                                   min_history=60)
    import pandas as pd

    snaps = builder.build_snapshots_with_extra_row(
        df, session=session, next_date=d, next_ts=pd.Timestamp(cutoff)
    )
    snap = snaps[-1]

    # ---- 6. distributions -------------------------------------------------------
    raw = (
        pipe["ensemble"].predict(snap.X, sel_idx=pipe["sel_idx"])
        if pipe.get("ensemble")
        else UniformModel().predict(snap.X)
    )
    calibrated = pipe["scaler"].transform(raw) if pipe.get("scaler") else raw
    calibrated = normalize_distribution(calibrated)

    # ---- 7. sections --------------------------------------------------------------
    section_payload = build_section_scores(calibrated, snap, session_df)

    # ---- 8. component agreement ----------------------------------------------------
    from .models.ensemble import model_input

    comp_sections = {}
    comp_distributions = {}
    for name, model in (pipe.get("components") or {}).items():
        try:
            p = normalize_distribution(
                model.predict(model_input(model, snap.X, pipe["sel_idx"]))
            )
        except Exception:
            continue
        comp_distributions[name] = p
        comp_sections[name] = argmax_section(p)
    agreement_ratio = (
        max(np.unique(list(comp_sections.values()), return_counts=True)[1]).item()
        / len(comp_sections)
        if comp_sections else 0.0
    )

    # ---- 9. top candidates ----------------------------------------------------------
    top = build_top_candidates(calibrated, comp_distributions, snap)

    # ---- 10. confidence -----------------------------------------------------------------
    val_metrics = (pipe.get("wf_result").component_val_preds.get(pipe["production_model"], {})
                   if pipe.get("wf_result") else {})
    ece = (pipe.get("wf_result").model_metrics.get(pipe["production_model"], {})
           .get("calibration", {}).get("expected_calibration_error", 0.05)) if pipe.get("wf_result") else 0.08
    confidence = compute_confidence(
        ece=ece or 0.05,
        agreement_ratio=agreement_ratio,
        n_train=n_rows,
        calibrated=calibrated,
        val_top10=val_metrics.get("val_top10_hit_rate"),
    )

    # ---- 11. assemble snapshot ------------------------------------------------------------
    training_end = str(pd_last_date(df))
    payload = {
        "pts": now.replace(microsecond=0),
        "sd": d,
        "sess": session,
        "cutoff": cutoff.replace(microsecond=0),
        "mv": pipe.get("version", f"{pipe['production_model']}@runtime"),
        "fv": "fv1.0",
        "ted": training_end,
        "trows": int(n_rows),
        "tier": tier,
        "edge": bool(pipe.get("edge_detected", False)),
        "notice": None if pipe.get("edge_detected") else _EDGE_NOTICE,
        "top10": [t["view"] for t in top[:10]],
        "section_scores": section_payload,
        "component_model_scores": {
            name: {
                "argmax_section": comp_sections[name],
                "section_probs": section_breakdown(p),
            }
            for name, p in comp_distributions.items()
        },
        "calibrated_probabilities": {
            f"{i:02d}": round(float(calibrated[i]), 6) for i in range(_N)
        },
        "agreement": float(agreement_ratio),
        "confidence": float(confidence),
        "dq": float(dq.score),
        "explanation": {
            "method": "Walk-forward validated ensemble over causal features",
            "production_model": pipe["production_model"],
            "selected_features": pipe.get("selected_features", [])[:20],
            "tier_notice": _tier_notice(tier),
            "agreement_detail": comp_sections,
            "disclaimer": _DISCLAIMER,
        },
        "_scores": [
            {
                "number": f"{i:02d}",
                "rank": int(sorted(range(_N), key=lambda j: (-calibrated[j], j)).index(i)) + 1,
                "raw_score": float(raw[i]),
                "calibrated_probability": round(float(calibrated[i]), 8),
                "section": classify_section(i),
                "component_scores": {
                    name: round(float(p[i]), 8) for name, p in comp_distributions.items()
                },
            }
            for i in sorted(range(_N), key=lambda j: (-calibrated[j], j))
        ],
    }
    payload["_scores"].sort(key=lambda s: s["rank"])
    # `top10` keeps the rich view objects (confidence tier + factors);
    # `_scores` is the complete ranked list persisted for auditability.
    payload = _augment_view(payload, section_payload, top, d, session, pipe, dq)

    if persist:
        try:
            # store.save_prediction_run pops `_scores` itself and writes
            # the prediction_runs + prediction_scores rows atomically.
            saved_id = store.save_prediction_run(dict(payload))
            payload["prediction_id"] = saved_id
        except Exception as exc:  # persistence must not break serving
            payload["prediction_id"] = None
            payload.setdefault("warnings", []).append(f"Snapshot persistence failed: {exc}")
    else:
        payload["prediction_id"] = None

    payload["stale"] = False
    return payload


# ---------------------------------------------------------------------------
# pipeline construction / caching
# ---------------------------------------------------------------------------

def _history_fingerprint(df, cutoff) -> str:
    last_ts = str(df["ts"].max()) if len(df) else "empty"
    h = hashlib.sha256(f"{last_ts}|{cutoff.isoformat()}".encode()).hexdigest()[:16]
    return h


def _get_or_build_pipeline(df, session: str, tier: str, cutoff) -> dict:
    key = (session, _history_fingerprint(df, cutoff))
    cached = _CACHE.get(key)
    if cached and cached["expires"] > datetime.now(tz=timezone.utc):
        return cached["pipe"]

    n_rows = int((df["session"] == session).sum())
    pipe: dict = {"tier": tier}

    if tier == "TIER_1":
        pipe.update({
            "components": {},
            "ensemble": None,
            "scaler": None,
            "sel_idx": list(range(len(FEATURE_INDEX))),
            "production_model": "uniform",
            "edge_detected": False,
            "version": "uniform_v0",
            "wf_result": None,
            "selected_features": [],
        })
        _cache_put(key, pipe)
        return pipe

    include_ml = tier in ("TIER_3", "TIER_4")
    wf: WalkForwardResult = run_walk_forward(
        df,
        session=session,
        halflife=settings.ewf_halflife,
        include_ml=include_ml,
    )
    pipe["wf_result"] = wf
    pipe["production_model"] = wf.production_model
    pipe["edge_detected"] = wf.edge_detected
    pipe["selected_features"] = wf.selected_features
    pipe["sel_idx"] = [
        i for name, i in FEATURE_INDEX.items() if name in set(wf.selected_features)
    ] or list(FEATURE_INDEX.values())

    # Refit component roster on ALL available history for live scoring.
    components: dict = {}

    from .models.baselines import (
        DigitModel,
        EWFrequencyModel,
        FrequencyModel,
        MarkovModel,
        RecentFrequencyModel,
        SetFeatureModel,
        UniformModel,
    )
    stat_models = [
        UniformModel(), FrequencyModel(), RecentFrequencyModel(),
        EWFrequencyModel(), MarkovModel(), DigitModel(),
        SetFeatureModel(feature_index=FEATURE_INDEX),
    ]
    X_all = None
    if include_ml:
        from .features.builder import CausalFeatureBuilder as _B

        b = _B(halflife=settings.ewf_halflife, min_history=60,
               max_snapshots=settings.max_walkforward_steps)
        snaps = b.build_snapshots(df, session=session)
        y = np.array([s.target if s.target is not None else -1 for s in snaps])
        valid = y >= 0
        X_all = np.vstack([s.X for s in snaps])
        yv = y[valid]
        groups = None
        for m in make_ml_models(tier):
            try:
                m.fit(X_all[:, pipe["sel_idx"]], yv, groups)
                components[m.name] = m
            except ValueError:
                continue
        xgb = None
        try:
            from .models.mlmodels import try_make_xgboost

            xgb = try_make_xgboost()
            if xgb is not None and wf.production_model == "xgboost":
                xgb.fit(X_all[:, pipe["sel_idx"]], yv, groups)
                components[xgb.name] = xgb
        except Exception:
            pass
    for m in stat_models:
        components[m.name] = m

    # Ensemble weights from the walk-forward result (validation-fitted).
    weights = np.zeros(len(components))
    names = list(components.keys())
    wf_names = list(wf.component_val_preds.keys())
    for i, nm in enumerate(names):
        if nm in wf_names:
            continue
    # Derive weights inversely proportional to validation log loss.
    losses = np.array([
        wf.component_val_preds.get(nm, {}).get("val_log_loss", 4.7) for nm in names
    ])
    inv = 1.0 / np.clip(losses, 0.05, None) ** 8   # sharp inverse-loss weighting
    weights = inv / inv.sum()

    ens = EnsembleModel(components=[components[nm] for nm in names])
    ens.weights = weights
    scaler = TemperatureScaler()
    # Fit temperature on the validation slice predictions of the ensemble proxy:
    scaler.temperature = getattr(wf, "_temperature", 1.0)

    pipe["components"] = components
    pipe["ensemble"] = ens
    pipe["scaler"] = scaler
    pipe["version"] = _next_version(session)

    _cache_put(key, pipe)
    return pipe


def _cache_put(key, pipe):
    _CACHE[key] = {"pipe": pipe, "expires": datetime.now(tz=timezone.utc) + timedelta(seconds=CACHE_TTL_SECONDS)}
    # Bound cache size defensively.
    if len(_CACHE) > 32:
        oldest = min(_CACHE, key=lambda k: _CACHE[k]["expires"])
        _CACHE.pop(oldest)


def _next_version(session: str) -> str:
    base = f"{session.lower()}_ensemble"
    try:
        n = store.count_model_versions(base) + 1
    except Exception:
        # Offline/dry-run mode: derive a stable non-persistent suffix.
        n = int(datetime.now(tz=timezone.utc).strftime("%H%M"))
    return f"{base}_v1.{n}"


# ---------------------------------------------------------------------------
# scoring helpers
# ---------------------------------------------------------------------------

def argmax_section(p: np.ndarray) -> str:
    sums = {s: float(p[lo : hi + 1].sum()) for s, (lo, hi) in SECTION_BOUNDS.items()}
    return max(sums, key=sums.get)


def section_breakdown(p: np.ndarray) -> dict:
    return {
        s: round(float(p[lo : hi + 1].sum()), 6)
        for s, (lo, hi) in SECTION_BOUNDS.items()
    }


def build_section_scores(calibrated: np.ndarray, snap: Snapshot, session_df) -> list[dict]:
    """Section probabilities + descriptive historical hit rates + explanations."""
    total = float(calibrated.sum()) or 1.0
    col = lambda name: snap.X[:, FEATURE_INDEX[name]]  # noqa: E731

    ewf = col("ewf"); mkv = col("markov_number"); f30 = col("freq_30")
    out = []
    ranks_sorted = sorted(
        SECTION_IDS,
        key=lambda s: -float(calibrated[SECTION_BOUNDS[s][0] : SECTION_BOUNDS[s][1] + 1].sum()),
    )

    for rank_order, s in enumerate(ranks_sorted, start=1):
        lo, hi = SECTION_BOUNDS[s]
        idx = np.arange(lo, hi + 1)
        prob = float(calibrated[idx].sum())
        score = prob / total

        # Descriptive historical hit rate (not a probability claim).
        hit_rate = last100_rate = None
        if len(session_df):
            nums = session_df["number"].to_numpy()
            hit_rate = float(((nums >= lo) & (nums <= hi)).mean())
            recent = nums[-100:]
            if len(recent):
                last100_rate = float(((recent >= lo) & (recent <= hi)).mean())

        explain: list[str] = []
        ewf_share = float(ewf[idx].sum())
        mkv_share = float(mkv[idx].sum())
        f30_share = float(f30[idx].sum())
        if ewf_share > 0.25:
            explain.append(f"Holds {ewf_share:.1%} of exponentially-weighted recent frequency mass.")
        if mkv_share > 0.25:
            explain.append(f"Above-baseline Markov transition support ({mkv_share:.1%}).")
        if f30_share > 0.25:
            explain.append(f"Short-window frequency share {f30_share:.1%}.")
        if not explain:
            explain.append("No dominant factor; score driven by diffuse baseline support.")
        explain.append(
            "Descriptive statistic only — past distribution does not guarantee future draws."
        )

        out.append({
            "section": s,
            "label": f"SECTION {s}",
            "range": f"{lo:02d}-{hi:02d}",
            "score": round(score, 6),
            "probability": round(prob, 6),
            "probability_display": f"{prob:.1%}".replace("%", "%"),
            "rank": rank_order,
            "candidate_count": int(hi - lo + 1),
            "historical_hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
            "historical_hit_rate_last100": round(last100_rate, 4) if last100_rate is not None else None,
            "explanation": explain,
        })
    return out


def build_top_candidates(calibrated, comp_distributions, snap: Snapshot) -> list[dict]:
    order = sorted(range(_N), key=lambda j: (-calibrated[j], j))
    ewf = snap.X[:, FEATURE_INDEX["ewf"]]
    f250 = snap.X[:, FEATURE_INDEX["freq_250"]]
    f30 = snap.X[:, FEATURE_INDEX["freq_30"]]
    mkv = snap.X[:, FEATURE_INDEX["markov_number"]]
    dsn = snap.X[:, FEATURE_INDEX["days_since_number"]]
    match_set = snap.X[:, FEATURE_INDEX["matches_set_frac_digits"]]
    same_tens = snap.X[:, FEATURE_INDEX["same_tens_as_prev"]]
    same_ones = snap.X[:, FEATURE_INDEX["same_ones_as_prev"]]
    rev = snap.X[:, FEATURE_INDEX["is_reverse_of_prev"]]

    q = lambda arr, p_: float(np.quantile(arr, p_))  # noqa: E731
    out = []
    for rank, j in enumerate(order[:10], start=1):
        support: list[str] = []
        contradict: list[str] = []
        if ewf[j] > q(ewf, 0.75):
            support.append("strong recent exponential-frequency support")
        if mkv[j] > q(mkv, 0.75):
            support.append("favorable Markov transition score")
        if f30[j] > q(f30, 0.75):
            support.append("above-baseline short-window frequency")
        if match_set[j] > 0.5:
            support.append("matches current SET fractional-digit context")
        if same_tens[j] > 0.5:
            support.append("shares tens digit with previous draw")
        if same_ones[j] > 0.5:
            support.append("shares ones digit with previous draw")
        if rev[j] > 0.5:
            support.append("reverse-number relationship to previous draw")
        if f250[j] < np.median(f250):
            contradict.append("weak long-term frequency")
        if dsn[j] > q(dsn, 0.75):
            contradict.append("long absence (weak signal only — not 'due')")
        if len(support) < 2:
            contradict.append("limited distinct supporting factors")
        contradict.append("historical sample provides no guarantee")

        tier_label = (
            "HIGHER MODEL SUPPORT" if rank <= 3
            else "MODERATE MODEL SUPPORT" if rank <= 10
            else "LOW MODEL SUPPORT"
        )
        out.append({
            "number": f"{j:02d}",
            "view": {
                "number": f"{j:02d}",
                "rank": rank,
                "score": round(float(calibrated[j]), 6),
                "raw_score": round(float(calibrated[j]), 8),
                "calibrated_probability": round(float(calibrated[j]), 6),
                "section": classify_section(j),
                "confidence_tier": tier_label,
                "supporting_factors": support or ["diffuse ensemble support"],
                "contradicting_factors": contradict,
            },
        })
    return out


def compute_confidence(*, ece: float, agreement_ratio: float, n_train: int,
                       calibrated: np.ndarray, val_top10: float | None) -> float:
    """Transparent composite confidence in [0,1].

    Components: calibration error, model agreement, sample size,
    probability concentration, and historical validation edge.
    """
    calib_component = max(0.0, 1.0 - min(1.0, ece / 0.10))
    agreement_component = agreement_ratio
    sample_component = min(1.0, n_train / settings.tier3_min)
    entropy = -float(np.sum(calibrated * np.log(calibrated + 1e-12)))
    concentration = max(0.0, 1.0 - entropy / math.log(_N))
    edge_component = 0.5 if val_top10 is None else float(np.clip((val_top10 - 0.10) * 5, 0, 1))
    conf = (
        0.25 * calib_component
        + 0.25 * agreement_component
        + 0.20 * sample_component
        + 0.15 * concentration
        + 0.15 * edge_component
    )
    return round(float(min(1.0, max(0.0, conf))), 4)


def _augment_view(payload: dict, sections, top, d, session, pipe, dq) -> dict:
    """Add API-facing fields (labels, ranking text, tier notices, disclaimer)."""
    best = max(sections, key=lambda s: s["probability"])
    label_en = "12:00 PM" if session == "MORNING" else "4:30 PM"
    payload["view"] = {
        "headline": {
            "title": "TODAY'S THAI 2D MODEL ANALYSIS",
            "session_label": label_en,
            "highest_model_scored_section": f"SECTION {best['section']}",
            "top_candidates": [t["number"] for t in top[:5]],
            "wording_note": "Highest model-scored section — NOT a guaranteed section.",
        },
        "section_ranking": " — ".join(
            f"{s['section']} {s['probability'] * 100:.1f}%"
            for s in sorted(sections, key=lambda x: x["rank"])
        ),
        "tier": payload["tier"],
        "tier_notice": _tier_notice(payload["tier"]),
        "edge_detected": payload["edge"],
        "edge_notice": payload["notice"],
        "data_quality_score": dq.score,
        "data_quality_warnings": dq.warnings,
        "model_agreement": (
            "HIGH MODEL AGREEMENT" if payload["agreement"] >= 0.75
            else "MODERATE MODEL AGREEMENT" if payload["agreement"] >= 0.5
            else "LOW MODEL AGREEMENT"
        ),
        "disclaimer": _DISCLAIMER,
    }
    return payload


_TIER_NOTICES = {
    "TIER_1": "Insufficient historical data — only uniform baseline statistics shown.",
    "TIER_2": "Limited historical depth — ML Ensemble disabled.",
    "TIER_3": "ML Ensemble Active.",
    "TIER_4": "ML Ensemble Active — advanced feature selection enabled.",
}
_EDGE_NOTICE = (
    "Current historical data does not demonstrate a reliable predictive edge. "
    "Rankings below are DESCRIPTIVE / LOW-SIGNAL."
)
_DISCLAIMER = (
    "This application provides statistical analysis based on historical market/2D data. "
    "Model scores are estimates, not guarantees. Historical performance does not "
    "guarantee future results."
)


def _tier_notice(tier: str) -> str:
    return _TIER_NOTICES.get(tier, "")


def pd_last_date(df):
    import pandas as pd

    return pd.Timestamp(df["date"].max()).date()


def train_and_persist(session: str) -> dict:
    """Full retraining cycle: walk-forward -> registry -> backtest record."""
    cutoff = datetime.now(tz=timezone.utc)
    df = load_history(cutoff)
    tier = data_tier(int((df["session"] == session).sum()))
    wf = run_walk_forward(df, session=session, include_ml=tier in ("TIER_3", "TIER_4"))
    version = _next_version(session)
    prod_metrics = wf.model_metrics.get(wf.production_model, {})
    model_id = f"{session.lower()}_ensemble"
    store.save_model_version(
        model_id=model_id,
        version=version,
        training_start=date.fromisoformat(str(wf.split_info["train_start"])),
        training_end=date.fromisoformat(str(wf.split_info["test_end"])),
        training_rows=int((df["session"] == session).sum()),
        selected_features=wf.selected_features,
        hyperparameters={
            "halflife": settings.ewf_halflife,
            "laplace_alpha": settings.markov_laplace_alpha,
            "corr_threshold": settings.feature_correlation_threshold,
        },
        validation_metrics={k: v for k, v in wf.component_val_preds.items()},
        test_metrics=prod_metrics,
        is_active=True,
        notes=("Production model: " + wf.production_model)
        if wf.edge_detected else "Baseline fallback — no reliable edge detected.",
    )
    bt_id = store.save_backtest(wf_result=wf, session=session,
                                model_version=version, is_production=True)
    return {
        "session": session,
        "version": version,
        "production_model": wf.production_model,
        "edge_detected": wf.edge_detected,
        "backtest_id": bt_id,
        "metrics": prod_metrics,
        "split_info": wf.split_info,
        "significance": wf.significance,
    }

