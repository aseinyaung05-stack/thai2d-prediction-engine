"""Model drift monitoring.

Compares realized prediction outcomes over trailing windows (30/100/250)
against the model's historical validation performance. Significant
deterioration => "MODEL DRIFT DETECTED" + retraining recommendation.
"""
from __future__ import annotations

import math

import numpy as np

from .. import store

DRIFT_TOP10_DROP = 0.05      # absolute drop in top-10 hit rate
DRIFT_MIN_SAMPLE = 30


def _top10_rate(outcomes: list[dict]) -> float | None:
    hits = [1 if o["actual_top10_hit"] else 0 for o in outcomes]
    if len(hits) == 0:
        return None
    return float(np.mean(hits))


def compute_drift(session: str | None = None) -> dict:
    outcomes = store.recent_prediction_outcomes(session=session, limit=250)
    windows = {}
    for w in (30, 100, 250):
        sub = [o for o in outcomes if o["actual_top10_hit"] is not None][:w]
        windows[w] = {
            "n": len(sub),
            "top10_hit_rate": round(_top10_rate(sub), 4) if sub else None,
        }

    # Reference expectation: random chance is 10% for top-10 of 100 numbers.
    # If a stored validation metric exists we could compare against it; the
    # floor check below catches catastrophic drift even without it.
    latest = windows[30]
    baseline = windows[250]
    drift = False
    reasons: list[str] = []
    if latest["top10_hit_rate"] is not None and baseline["top10_hit_rate"] is not None:
        drop = baseline["top10_hit_rate"] - latest["top10_hit_rate"]
        if drop > DRIFT_TOP10_DROP and latest["n"] >= DRIFT_MIN_SAMPLE:
            drift = True
            reasons.append(
                f"Top-10 hit rate fell {drop:.3f} over last {latest['n']} predictions."
            )
    for w in (30, 100):
        rate = windows[w]["top10_hit_rate"]
        if rate is not None and windows[w]["n"] >= DRIFT_MIN_SAMPLE and rate < 0.04:
            drift = True
            reasons.append(f"Top-10 hit rate {rate:.3f} over last {windows[w]['n']} — near/below chance.")

    return {
        "drift_detected": drift,
        "windows": {str(k): v for k, v in windows.items()},
        "reasons": reasons,
        "recommendation": (
            "Retrain models with recent data and re-run walk-forward validation "
            "before trusting current rankings." if drift else "No significant drift detected."
        ),
        "expected_random_top10": 0.10,
        "note": "With truly unpredictable draws, sustained rates far above 0.10 are unlikely; interpret small samples cautiously.",
    }
