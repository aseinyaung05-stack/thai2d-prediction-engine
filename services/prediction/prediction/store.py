"""Persistence for model versions, backtests and prediction snapshots.

Uses raw SQLAlchemy Core against the snake_case schema shared with Prisma.
Every write is append-only: previous model/backtest rows are never mutated.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import date, datetime

import numpy as np
from sqlalchemy import create_engine, text

from .config import settings

_engine = None


def _new_id() -> str:
    """Prisma-style cuid surrogate: the @default(cuid()) lives in the Prisma
    client, not the database, so raw-SQL inserts must generate their own."""
    return f"c{int(time.time() * 1000):x}{uuid.uuid4().hex[:14]}"


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def _j(obj) -> str:
    """JSON-safe serializer (dates, numpy scalars, arrays)."""

    def default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return str(o)

    return json.dumps(obj, default=default)


# --------------------------------------------------------------------------
# model registry
# --------------------------------------------------------------------------

def save_model_version(
    *,
    model_id: str,
    version: str,
    training_start: date,
    training_end: date,
    training_rows: int,
    selected_features: list[str],
    hyperparameters: dict,
    validation_metrics: dict,
    test_metrics: dict,
    is_active: bool,
    notes: str | None = None,
) -> str:
    with _get_engine().begin() as conn:
        conn.execute(text("UPDATE model_versions SET is_active = FALSE WHERE model_id = :mid"),
                     {"mid": model_id})
        row = conn.execute(
            text(
                """
                INSERT INTO model_versions
                  (id, model_id, version, training_start, training_end, training_rows,
                   selected_features, hyperparameters, validation_metrics, test_metrics,
                   is_active, notes)
                VALUES (:id, :model_id, :version, :training_start, :training_end, :training_rows,
                        CAST(:selected_features AS jsonb), CAST(:hyperparameters AS jsonb),
                        CAST(:validation_metrics AS jsonb), CAST(:test_metrics AS jsonb),
                        :is_active, :notes)
                RETURNING id
                """
            ),
            {
                "id": _new_id(),
                "model_id": model_id,
                "version": version,
                "training_start": training_start,
                "training_end": training_end,
                "training_rows": training_rows,
                "selected_features": _j(selected_features),
                "hyperparameters": _j(hyperparameters),
                "validation_metrics": _j(validation_metrics),
                "test_metrics": _j(test_metrics),
                "is_active": is_active,
                "notes": notes,
            },
        )
        return row.scalar_one()


def get_active_model(model_id: str) -> dict | None:
    with _get_engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT * FROM model_versions WHERE model_id = :mid AND is_active = TRUE "
                "ORDER BY creation_timestamp DESC LIMIT 1"
            ),
            {"mid": model_id},
        ).mappings().first()
    return dict(row) if row else None


def count_model_versions(model_id: str) -> int:
    with _get_engine().connect() as conn:
        n = conn.execute(
            text("SELECT COUNT(*) FROM model_versions WHERE model_id = :mid"),
            {"mid": model_id},
        ).scalar()
    return int(n or 0)


# --------------------------------------------------------------------------
# backtests
# --------------------------------------------------------------------------

def save_backtest(*, wf_result, session: str, model_version: str, is_production: bool) -> str:
    s = wf_result.split_info
    prod = wf_result.model_metrics.get(wf_result.production_model, {})
    baseline_comparison = {
        name: {
            "val_log_loss": wf_result.component_val_preds.get(name, {}).get("val_log_loss"),
        }
        for name in ("uniform", "frequency", "recent_frequency", "ew_frequency")
    }
    with _get_engine().begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO backtests
                  (id, model_version, model_name, feature_version, train_start, train_end,
                   validation_start, validation_end, test_start, test_end, n_predictions,
                   metrics, baseline_comparison, is_production)
                VALUES (:id, :mv, :mn, 'fv1.0', :ts, :te, :vs, :ve, :tss, :tse, :n,
                        CAST(:metrics AS jsonb), CAST(:baseline AS jsonb), :is_prod)
                RETURNING id
                """
            ),
            {
                "id": _new_id(),
                "mv": model_version,
                "mn": wf_result.production_model,
                "ts": s["train_start"],
                "te": s["train_end"],
                "vs": s["train_end"],
                "ve": s["validation_end"],
                "tss": s["validation_end"],
                "tse": s["test_end"],
                "n": int(s["test_points"]),
                "metrics": _j(prod),
                "baseline": _j(baseline_comparison),
                "is_prod": is_production,
            },
        )
        return row.scalar_one()


# --------------------------------------------------------------------------
# prediction snapshots
# --------------------------------------------------------------------------

def save_prediction_run(payload: dict) -> str:
    scores = payload.pop("_scores")
    with _get_engine().begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO prediction_runs
                  (id, prediction_timestamp_utc, session_date, session, source_data_cutoff_utc,
                   model_version, feature_version, training_data_end_date, training_rows,
                   data_tier, edge_detected, edge_notice, top10, section_scores,
                   component_model_scores, calibrated_probabilities, model_agreement_ratio,
                   model_confidence, data_quality_score, explanation)
                VALUES (:id, :pts, :sd, CAST(:sess AS session_enum), :cutoff,
                        :mv, :fv, :ted, :trows, :tier, :edge, :notice,
                        CAST(:top10 AS jsonb), CAST(:sections AS jsonb),
                        CAST(:components AS jsonb), CAST(:calib AS jsonb),
                        :agreement, :confidence, :dq, CAST(:explanation AS jsonb))
                RETURNING id
                """
            ),
            {
                "id": _new_id(),
                **{k: payload[k] for k in (
                    "pts", "sd", "sess", "cutoff", "mv", "fv", "ted", "trows",
                    "tier", "edge", "notice",
                )},
                "top10": _j(payload["top10"]),
                "sections": _j(payload["section_scores"]),
                "components": _j(payload["component_model_scores"]),
                "calib": _j(payload["calibrated_probabilities"]),
                "agreement": payload["agreement"],
                "confidence": payload["confidence"],
                "dq": payload["dq"],
                "explanation": _j(payload["explanation"]),
            },
        )
        run_id = row.scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO prediction_scores
                  (id, run_id, number, rank, raw_score, calibrated_probability, section, component_scores)
                SELECT 'c' || floor(extract(epoch FROM clock_timestamp()) * 1000)::text
                         || substr(md5(random()::text || s.ord::text), 1, 12),
                       :run_id, CAST(s.x->>'number' AS text), (s.x->>'rank')::int,
                       (s.x->>'raw_score')::float8, (s.x->>'calibrated_probability')::float8,
                       LEFT(s.x->>'section', 1), CAST(s.x->>'component_scores' AS jsonb)
                FROM jsonb_array_elements(CAST(:scores AS jsonb)) WITH ORDINALITY AS s(x, ord)
                """
            ),
            {"run_id": run_id, "scores": _j(scores)},
        )
    return run_id


def recent_prediction_outcomes(session: str | None = None, limit: int = 250) -> list[dict]:
    sql = text(
        """
        SELECT pr.id, pr.prediction_timestamp_utc, pr.session::text AS session,
               pr.session_date, pr.actual_rank, pr.actual_top10_hit,
               pr.edge_detected, pr.model_confidence
        FROM prediction_runs pr
        WHERE pr.actual_result IS NOT NULL
          AND (:sess IS NULL OR pr.session::text = :sess)
        ORDER BY pr.source_data_cutoff_utc DESC
        LIMIT :lim
        """
    )
    with _get_engine().connect() as conn:
        rows = conn.execute(sql, {"sess": session, "lim": limit}).mappings().all()
    return [dict(r) for r in rows]

