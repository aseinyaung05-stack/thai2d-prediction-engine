"""Shared fixtures: deterministic MOCK/test-only history generator.

Clearly separated so production paths can never silently consume it
(spec: NO FABRICATED DATA — tests inject this explicitly).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

UTC = timezone.utc


def make_history(
    n_days: int = 320,
    end: datetime | None = None,
    seed: int = 7,
    biased_session: str | None = "MORNING",
    favorite_numbers: tuple[int, ...] = (13, 27, 55),
) -> pd.DataFrame:
    """Deterministic synthetic 2D history for tests ONLY.

    Produces Mon-Fri draws at the Yangon session instants (05:30/10:00 UTC).
    When `biased_session` is set, that stream slightly over-samples the
    favorite numbers so frequency models have learnable signal.
    """
    rng = np.random.default_rng(seed)
    end = end or datetime.now(tz=UTC)
    rows = []
    day = (end - timedelta(days=n_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    while day < end:
        wd = day.weekday()
        if wd < 5:
            # Source events occur shortly before each Yangon cutoff:
            #   MORNING cutoff 05:30 UTC -> event 05:00 UTC
            #   AFTERNOON cutoff 10:00 UTC -> event 09:30 UTC
            for session, utc_h, utc_m in (("MORNING", 5, 0), ("AFTERNOON", 9, 30)):
                ts = day.replace(hour=utc_h, minute=utc_m, tzinfo=UTC)
                if ts >= end:
                    continue
                if biased_session == session and rng.random() < 0.25:
                    num = int(rng.choice(favorite_numbers))
                else:
                    num = int(rng.integers(0, 100))
                rows.append(
                    {
                        "ts": pd.Timestamp(ts),
                        "date": day.date(),
                        "session": session,
                        "number": num,
                        "tens": num // 10,
                        "ones": num % 10,
                        "set_value": round(1200 + rng.normal(0, 15) + (num % 10) * 0.01, 2),
                        "market_value": round(1150 + rng.normal(0, 20), 2),
                    }
                )
        day += timedelta(days=1)
    return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)


@pytest.fixture(scope="session")
def history_df() -> pd.DataFrame:
    return make_history()


class MockRepository:
    """Test repository mirroring repository.load_history semantics."""

    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def load_history(self, end_cutoff_utc, session=None, start_date=None) -> pd.DataFrame:
        df = self.frame[self.frame["ts"] <= pd.Timestamp(end_cutoff_utc)].copy()
        if session is not None:
            df = df[df["session"] == session]
        if start_date is not None:
            df = df[df["date"] >= pd.Timestamp(start_date).date()]
        return df.sort_values("ts").reset_index(drop=True)

    def count_history(self, end_cutoff_utc) -> int:
        return len(self.load_history(end_cutoff_utc))

    def __call__(self, cutoff, session=None):
        return self.load_history(cutoff, session=session)


@pytest.fixture(scope="session")
def mock_repo(history_df):
    return MockRepository(history_df)
