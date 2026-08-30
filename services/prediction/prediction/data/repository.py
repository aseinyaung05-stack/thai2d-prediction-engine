"""Chronological data access for the prediction engine.

All queries enforce a hard source_data_cutoff_utc: no observation with a
source timestamp after the cutoff can ever reach feature generation
(data-leakage prevention, spec: STRICT DATA LEAKAGE).
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine, text

from ..config import settings

_RESULT_COLUMNS = [
    "ts",            # source_timestamp (UTC)
    "date",          # Myanmar-local session date
    "session",       # MORNING / AFTERNOON
    "number",        # int 0..99 (parsed from zero-padded twod)
    "tens",
    "ones",
    "set_value",
    "market_value",
]

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def load_history(
    end_cutoff_utc: datetime,
    session: str | None = None,
    start_date=None,
) -> pd.DataFrame:
    """Load results with source timestamp <= cutoff, chronologically sorted.

    `session` restricts to one draw stream when set; cross-session features
    call it with session=None to interleave both streams.
    """
    sql = text(
        """
        SELECT source_timestamp AS ts,
               date,
               session::text  AS session,
               twod,
               digit_tens     AS tens,
               digit_ones     AS ones,
               set_value,
               market_value
        FROM results
        WHERE source_timestamp <= :cutoff
          AND (:start_date IS NULL OR date >= :start_date)
          AND (:session IS NULL OR session::text = :session)
        ORDER BY source_timestamp ASC
        """
    )
    with _get_engine().connect() as conn:
        df = pd.read_sql_query(
            sql,
            conn,
            params={
                "cutoff": end_cutoff_utc,
                "start_date": start_date,
                "session": session,
            },
        )
    if df.empty:
        return pd.DataFrame(columns=_RESULT_COLUMNS)

    df["number"] = df["twod"].astype(str).str.zfill(2).astype(int)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df[_RESULT_COLUMNS]


def count_history(end_cutoff_utc: datetime) -> int:
    with _get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT COUNT(*) FROM results WHERE source_timestamp <= :c"),
            {"c": end_cutoff_utc},
        ).scalar()
    return int(row or 0)


def find_duplicates() -> pd.DataFrame:
    """True duplicates: same Myanmar-local date AND session with identical
    result (cross-session repeats are legitimate)."""
    sql = text(
        """
        SELECT date, session::text AS session, twod, COUNT(*) AS n
        FROM results
        GROUP BY date, session, twod
        HAVING COUNT(*) >= 2
        ORDER BY date DESC
        LIMIT 200
        """
    )
    with _get_engine().connect() as conn:
        return pd.read_sql_query(sql, conn)


class MockRepository:
    """TEST-ONLY repository fed from an in-memory DataFrame.

    Clearly separated so production code paths can never silently consume
    fabricated data — tests inject this explicitly.
    """

    def __init__(self, frame: pd.DataFrame):
        self.frame = frame.copy()

    def load_history(self, end_cutoff_utc, session=None, start_date=None) -> pd.DataFrame:
        df = self.frame[self.frame["ts"] <= end_cutoff_utc].copy()
        if session is not None:
            df = df[df["session"] == session]
        if start_date is not None:
            df = df[df["date"] >= start_date]
        return df.sort_values("ts").reset_index(drop=True)[_RESULT_COLUMNS]

    def count_history(self, end_cutoff_utc) -> int:
        return len(self.load_history(end_cutoff_utc))
