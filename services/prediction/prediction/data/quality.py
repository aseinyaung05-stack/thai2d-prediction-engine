"""Data-quality scoring and the pre-prediction validation gate."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from ..config import settings


@dataclass
class QualityReport:
    score: int
    total_records: int
    duplicate_count: int
    missing_sessions: int
    future_timestamps: int
    stale_hours: float | None
    warnings: list[str] = field(default_factory=list)


def compute_quality(df: pd.DataFrame, now: datetime | None = None) -> QualityReport:
    now = now or pd.Timestamp.now(tz="UTC").to_pydatetime()
    warnings: list[str] = []

    total = len(df)
    if total == 0:
        return QualityReport(0, 0, 0, 0, 0, None, ["No historical data available."])

    # True duplicates = same Myanmar-local date AND session with identical
    # result. The same number appearing in MORNING and AFTERNOON is normal,
    # not an error.
    duplicates = int(df.duplicated(subset=["date", "session", "number"]).sum())
    future_ts = int((pd.to_datetime(df["ts"], utc=True) > pd.Timestamp(now) + pd.Timedelta(minutes=5)).sum())

    # Missing sessions: group by Myanmar-local date; trading days (Mon-Fri)
    # should contain both sessions.
    dates = pd.to_datetime(df["date"])
    by_day = df.assign(d=dates).groupby("d")["session"].nunique()
    weekday_days = [d for d in by_day.index if d.weekday() < 5]
    missing_sessions = sum(1 for d in weekday_days if by_day[d] < 2)

    latest_ts = pd.to_datetime(df["ts"], utc=True).max().to_pydatetime()
    stale_hours = max(0.0, (now - latest_ts).total_seconds() / 3600.0)

    w_dup = min(1.0, duplicates / max(20, total * 0.02))
    w_missing = min(1.0, missing_sessions / 40)
    w_future = min(1.0, future_ts / 5)
    w_stale = min(1.0, stale_hours / 72)

    score = round(
        100
        * (
            0.35 * (1 - w_dup)
            + 0.25 * (1 - w_missing)
            + 0.15 * (1 - w_future)
            + 0.25 * (1 - w_stale)
        )
    )

    if score < 90:
        warnings.append("Data quality below 90% — treat analysis with caution.")
    if stale_hours > 72:
        warnings.append("Source data appears stale (>72h). Prediction may be outdated.")
    if duplicates > 0:
        warnings.append(f"{duplicates} duplicate date+result rows detected.")

    return QualityReport(score, total, duplicates, missing_sessions, future_ts,
                         round(stale_hours, 1), warnings)


def quality_gate(df: pd.DataFrame, now: datetime | None = None) -> tuple[bool, list[str]]:
    """Hard gate before prediction generation.

    Returns (passed, failure_reasons). When failed, callers must NOT produce a
    normal prediction ("Prediction unavailable because data validation failed.").
    """
    rep = compute_quality(df, now)
    reasons: list[str] = []
    if rep.total_records < settings.tier2_min:
        reasons.append(
            f"Only {rep.total_records} valid records (<{settings.tier2_min} minimum)."
        )
    if rep.future_timestamps > 0:
        reasons.append(f"{rep.future_timestamps} future timestamps found.")
    if settings.strict_validation and rep.stale_hours is not None and rep.stale_hours > 96:
        reasons.append("Source data older than 96 hours.")
    return len(reasons) == 0, reasons


def data_tier(total_records: int) -> str:
    """Cold-start strategy tiers (spec: COLD START STRATEGY)."""
    if total_records < settings.tier2_min:
        return "TIER_1"
    if total_records < settings.tier3_min:
        return "TIER_2"
    if total_records < settings.tier4_min:
        return "TIER_3"
    return "TIER_4"
