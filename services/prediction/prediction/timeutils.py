"""Timezone-aware session logic.

Canonical storage/computation is UTC. User-facing prediction sessions are
defined in Asia/Yangon; Thai source events originate in Asia/Bangkok.
NEVER add/subtract fixed hour offsets — always use zoneinfo conversions.
"""
from __future__ import annotations

from datetime import date, datetime, time as dt_time
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")
BANGKOK = ZoneInfo("Asia/Bangkok")   # Thailand: UTC+07:00 (no DST)
YANGON = ZoneInfo("Asia/Yangon")     # Myanmar:  UTC+06:30 (no DST)

SESSION_TIMES_YANGON: dict[str, dt_time] = {
    "MORNING": dt_time(12, 0),      # 12:00 PM Myanmar time
    "AFTERNOON": dt_time(16, 30),   # 4:30 PM Myanmar time
}
SESSIONS = ("MORNING", "AFTERNOON")

#: Thai SET is closed on Saturday/Sunday -> no 2D draws.
WEEKEND_WEEKDAYS = (5, 6)  # Monday=0 ... Saturday=5, Sunday=6


def is_weekend(d: date) -> bool:
    return d.weekday() in WEEKEND_WEEKDAYS


def next_session_date_for(session: str, now: datetime | None = None) -> date:
    """Next Myanmar-local trading day hosting `session` (weekends skipped).

    If today is a trading day but this session's cutoff already passed,
    the next trading day is returned instead.
    """
    from datetime import timedelta

    now = now or datetime.now(tz=UTC)
    d = yangon_today(now)
    for i in range(0, 8):
        dd = d + timedelta(days=i)
        if is_weekend(dd):
            continue
        if i == 0 and session_cutoff_utc(dd, session) <= now:
            continue
        return dd
    return d


def session_cutoff_utc(session_date: date, session: str) -> datetime:
    """Exact UTC instant of the Yangon-local draw moment for a session.

    The model may only use source data with timestamp <= this cutoff.
    """
    if session not in SESSION_TIMES_YANGON:
        raise ValueError(f"Unknown session: {session}")
    local_dt = datetime.combine(session_date, SESSION_TIMES_YANGON[session], tzinfo=YANGON)
    return local_dt.astimezone(UTC)


def yangon_today(now: datetime | None = None) -> date:
    now = now or datetime.now(tz=UTC)
    return now.astimezone(YANGON).date()


def current_or_next_session(now: datetime | None = None) -> tuple[date, str, datetime]:
    """Return (sessionDate, session, cutoffUtc) for the next upcoming draw.

    Weekend-aware: Thai SET is closed Sat/Sun, so the next draw is always on
    a weekday (Mon 12:00 PM Yangon after Friday's afternoon session).
    """
    now = now or datetime.now(tz=UTC)
    d = yangon_today(now)
    if is_weekend(d):
        nd = next_session_date_for("MORNING", now)
        return nd, "MORNING", session_cutoff_utc(nd, "MORNING")
    for s in SESSIONS:
        cut = session_cutoff_utc(d, s)
        if cut > now:
            return d, s, cut
    # Both of today's sessions drawn -> next trading day's MORNING.
    nd = next_session_date_for("MORNING", now)
    return nd, "MORNING", session_cutoff_utc(nd, "MORNING")


def to_yangon(dt: datetime) -> datetime:
    return dt.astimezone(YANGON)


def derive_session_from_timestamp(ts_utc: datetime) -> tuple[date, str]:
    """Map a source-market instant to the Myanmar-local prediction session.

    Yangon wall-clock hour < 15 -> MORNING else AFTERNOON. This correctly
    handles the Bangkok(UTC+7) -> Yangon(UTC+6:30) offset difference.
    """
    local = ts_utc.astimezone(YANGON)
    session = "MORNING" if local.hour < 15 else "AFTERNOON"
    return local.date(), session
