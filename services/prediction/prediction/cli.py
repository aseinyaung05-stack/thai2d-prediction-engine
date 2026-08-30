"""CLI for first-run pipeline, backtesting and one-off predictions.

Usage:
  python -m prediction.cli full-run      # first-run experience (spec §44)
  python -m prediction.cli backtest MORNING
  python -m prediction.cli predict MORNING
  python -m prediction.cli drift
"""
from __future__ import annotations

import argparse
import json
import sys

STEPS = [
    "DATA IMPORT",
    "DATA VALIDATION",
    "FEATURE ENGINEERING",
    "BACKTEST",
    "MODEL TRAINING",
    "MODEL SELECTION",
    "TODAY'S ANALYSIS",
]


def _step(name: str, ok: bool, detail: str = "") -> None:
    mark = "✓" if ok else "✗"
    print(f"{name} {mark} {detail}")


def cmd_full_run(args):
    from .data.quality import compute_quality, data_tier
    from .data.repository import load_history
    from .timeutils import session_cutoff_utc, yangon_today

    print("=== Thai 2D Prediction Engine — first-run pipeline ===")
    today = yangon_today()

    # 1. DATA IMPORT — the API ingestion service owns fetching; here we verify.
    cutoff_m = session_cutoff_utc(today, "MORNING")
    df = load_history(cutoff_m)
    _step("DATA IMPORT", len(df) > 0, f"{len(df)} rows visible at cutoff")

    # 2. DATA VALIDATION
    q = compute_quality(df)
    _step("DATA VALIDATION", q.score >= 60, f"quality={q.score}/100 records={q.total_records}")
    for w in q.warnings:
        print(f"   ! {w}")

    for s in ("MORNING", "AFTERNOON"):
        cutoff = session_cutoff_utc(today, s)
        sdf = load_history(cutoff)
        n = int((sdf["session"] == s).sum())
        tier = data_tier(n)
        print(f"\n--- {s} session: {n} records, tier={tier} ---")

        # 3-6. features/backtest/training/selection via walk-forward.
        from .backtest.walkforward import run_walk_forward

        wf = run_walk_forward(sdf, session=s, include_ml=tier in ("TIER_3", "TIER_4"))
        _step("FEATURE ENGINEERING", True,
              f"{len(wf.selected_features)} selected features")
        prod = wf.model_metrics.get(wf.production_model, {})
        _step("BACKTEST", prod.get("n_predictions", 0) > 0,
              f"test_points={wf.split_info['test_points']}")
        _step("MODEL TRAINING", True, f"components={len(wf.component_val_preds)}")
        _step("MODEL SELECTION", True,
              f"production={wf.production_model} edge={wf.edge_detected}")
        if not wf.edge_detected:
            print("   ! No reliable predictive edge detected — baseline retained.")

        # 7. Persist registry + backtest, generate today's analysis.
        from . import engine

        result = engine.train_and_persist(s)
        payload = engine.generate_prediction(s, session_date=today, persist=True)
        headline = payload["view"]["headline"]
        print(f"   {label(s)} — Highest model-scored section: "
              f"{headline['highest_model_scored_section']}; "
              f"Top candidates: {' '.join(headline['top_candidates'])}")
    _step("TODAY'S ANALYSIS", True, "prediction snapshots persisted")
    print("\nDone. Disclaimer: model scores are estimates, not guarantees.")


def label(s):
    return "12:00 PM" if s == "MORNING" else "4:30 PM"


def cmd_backtest(args):
    from . import engine

    out = engine.train_and_persist(args.session.upper())
    print(json.dumps(out, indent=2, default=str))


def cmd_predict(args):
    from . import engine
    from .timeutils import yangon_today

    payload = engine.generate_prediction(args.session.upper(), session_date=yangon_today(),
                                         persist=False)
    slim = {
        "session": payload["sess"],
        "date": str(payload["sd"]),
        "tier": payload["tier"],
        "edge_detected": payload["edge"],
        "sections": payload["view"]["section_ranking"],
        "top10": payload["top10"],
        "disclaimer": payload["explanation"]["disclaimer"],
    }
    print(json.dumps(slim, indent=2, default=str))


def cmd_drift(args):
    from .monitoring.drift import compute_drift

    print(json.dumps(compute_drift(args.session), indent=2, default=str))


def main(argv=None):
    p = argparse.ArgumentParser("prediction")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("full-run")
    bt = sub.add_parser("backtest")
    bt.add_argument("session", choices=["MORNING", "AFTERNOON"])
    pr = sub.add_parser("predict")
    pr.add_argument("session", choices=["MORNING", "AFTERNOON"])
    dr = sub.add_parser("drift")
    dr.add_argument("--session", default=None)
    args = p.parse_args(argv)
    {"full-run": cmd_full_run, "backtest": cmd_backtest,
     "predict": cmd_predict, "drift": cmd_drift}[args.cmd](args)


if __name__ == "__main__":
    main(sys.argv[1:])
