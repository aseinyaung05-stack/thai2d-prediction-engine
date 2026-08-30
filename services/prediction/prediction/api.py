"""FastAPI service exposing the prediction engine.

Auth: Bearer token (PREDICTION_API_TOKEN) on all endpoints except /health.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from . import engine, store
from .config import settings
from .data.repository import find_duplicates
from .monitoring.drift import compute_drift
from .timeutils import SESSIONS, current_or_next_session, session_cutoff_utc, to_yangon

app = FastAPI(
    title="Thai 2D Prediction Engine",
    version="1.0.0",
    description=(
        "Statistical analysis of historical Thai 2D results. Model scores are "
        "estimates — NOT guarantees. Educational/research use only."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # token-gated internal service; tighten per deployment
    allow_methods=["GET", "POST"],
)

bearer = HTTPBearer(auto_error=False)


def require_token(cred: HTTPAuthorizationCredentials | None = Security(bearer)):
    if cred is None or cred.credentials != settings.api_token:
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")
    return cred


def _session_or_400(session: str) -> str:
    s = session.upper()
    if s not in SESSIONS:
        raise HTTPException(status_code=400, detail="session must be MORNING or AFTERNOON")
    return s


@app.get("/health")
def health():
    nxt_date, nxt_session, cutoff = current_or_next_session()
    return {
        "status": "ok",
        "time_utc": datetime.utcnow().isoformat() + "Z",
        "time_yangon": to_yangon(datetime.now(tz=__import__("zoneinfo").ZoneInfo("UTC"))).strftime(
            "%Y-%m-%d %H:%M MM"
        ),
        "next_session": {
            "date": str(nxt_date),
            "session": nxt_session,
            "cutoff_utc": cutoff.isoformat(),
        },
        "disclaimer": engine._DISCLAIMER,
    }


@app.get("/predict/{session}")
def predict_session(session: str, d: date | None = Query(None, alias="date"),
                    token: dict = Depends(require_token)):
    s = _session_or_400(session)
    try:
        return engine.generate_prediction(s, session_date=d)
    except engine.PredictionUnavailable as e:
        raise HTTPException(status_code=422, detail={"error": str(e), "reasons": e.reasons})


@app.get("/predict/{session}/top")
def predict_top(session: str, n: int = Query(10, ge=1, le=50),
                token: dict = Depends(require_token)):
    s = _session_or_400(session)
    payload = engine.generate_prediction(s)
    scores = payload.get("_scores", [])
    return {"session": s, "top": scores[:n], "edge_detected": payload.get("edge")}


@app.get("/predict/{session}/sections")
def predict_sections(session: str, token: dict = Depends(require_token)):
    s = _session_or_400(session)
    payload = engine.generate_prediction(s)
    return {
        "session": s,
        "sections": payload["section_scores"],
        "section_ranking": payload["view"]["section_ranking"],
        "highest_model_scored_section": payload["view"]["headline"]["highest_model_scored_section"],
    }


class BacktestRequest(BaseModel):
    session: str = "MORNING"
    max_steps: int | None = None


@app.post("/backtest/run")
def run_backtest(req: BacktestRequest, token: dict = Depends(require_token)):
    """Full walk-forward evaluation + model registry update (long-running)."""
    from .backtest.walkforward import run_walk_forward
    from .data.repository import load_history
    from .data.quality import data_tier
    from .config import settings as cfg

    s = _session_or_400(req.session)
    cutoff = datetime.now().astimezone(tz=None)  # naive local == UTC container
    from .timeutils import yangon_today, session_cutoff_utc

    cutoff = session_cutoff_utc(yangon_today(), s)
    df = load_history(cutoff)
    tier = data_tier(int((df["session"] == s).sum()))
    wf = run_walk_forward(df, session=s, include_ml=tier in ("TIER_3", "TIER_4"))
    version = engine._next_version(s)
    prod_metrics = wf.model_metrics.get(wf.production_model, {})
    model_id = f"{s.lower()}_ensemble"
    mv_id = store.save_model_version(
        model_id=model_id,
        version=version,
        training_start=date.fromisoformat(str(wf.split_info["train_start"])),
        training_end=date.fromisoformat(str(wf.split_info["test_end"])),
        training_rows=int((df["session"] == s).sum()),
        selected_features=wf.selected_features,
        hyperparameters={
            "halflife": cfg.ewf_halflife,
            "laplace_alpha": cfg.markov_laplace_alpha,
            "corr_threshold": cfg.feature_correlation_threshold,
        },
        validation_metrics={k: v for k, v in wf.component_val_preds.items()},
        test_metrics=prod_metrics,
        is_active=True,
        notes=("Production model: " + wf.production_model) if wf.edge_detected
        else "Baseline fallback — no reliable edge detected.",
    )
    bt_id = store.save_backtest(wf_result=wf, session=s, model_version=version, is_production=True)
    return {
        "ok": True,
        "model_version_id": mv_id,
        "backtest_id": bt_id,
        "version": version,
        "production_model": wf.production_model,
        "edge_detected": wf.edge_detected,
        "metrics": prod_metrics,
        "significance": wf.significance,
        "split_info": wf.split_info,
        "segment_performance": wf.segment_performance,
        "rolling_performance": wf.rolling_performance,
    }


@app.get("/monitor/drift")
def drift(session: str | None = None, token: dict = Depends(require_token)):
    return compute_drift(session.upper() if session else None)


@app.get("/data/quality")
def duplicates(token: dict = Depends(require_token)):
    try:
        df = find_duplicates()
        return {"duplicate_groups": len(df), "rows": df.to_dict(orient="records")}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


@app.post("/internal/retrain-hook")
async def retrain_hook(reason: dict, background: dict = None):
    """Called by the API scheduler after new data lands.

    Fire-and-forget retrain for both sessions; failures are logged not raised.
    """
    results = {}

    async def _retrain():
        for s in ("MORNING", "AFTERNOON"):
            try:
                results[s] = await asyncio.to_thread(engine.train_and_persist, s)
            except Exception as exc:
                results[s] = {"error": str(exc)}

    asyncio.create_task(_retrain())
    return {"accepted": True, "reason": reason}
