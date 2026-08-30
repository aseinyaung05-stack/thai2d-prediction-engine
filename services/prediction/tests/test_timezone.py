"""Timezone handling (Asia/Yangon sessions vs Asia/Bangkok source)."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from prediction.timeutils import (
    BANGKOK,
    YANGON,
    current_or_next_session,
    derive_session_from_timestamp,
    session_cutoff_utc,
)
from datetime import date


def test_morning_cutoff_is_0530_utc():
    cut = session_cutoff_utc(date(2026, 8, 23), "MORNING")
    assert cut == datetime(2026, 8, 23, 5, 30, tzinfo=timezone.utc)


def test_afternoon_cutoff_is_1000_utc():
    cut = session_cutoff_utc(date(2026, 8, 23), "AFTERNOON")
    assert cut == datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)


def test_yangon_offset_is_630_not_600():
    """Myanmar is UTC+06:30 — a fixed +6 offset would be wrong."""
    utc = datetime(2026, 1, 1, 5, 30, tzinfo=timezone.utc)
    local = utc.astimezone(YANGON)
    assert (local.hour, local.minute) == (12, 0)


def test_bangkok_vs_yangon_source_times():
    """12:31 Bangkok == 12:01 Yangon -> still MORNING (< 15:00 rule)."""
    bangkok_noon = datetime(2026, 8, 21, 12, 31, tzinfo=BANGKOK)
    d, s = derive_session_from_timestamp(bangkok_noon)
    assert s == "MORNING"
    assert str(d) == "2026-08-21"

    bangkok_eve = datetime(2026, 8, 21, 16, 33, tzinfo=BANGKOK)  # 16:03 Yangon
    d2, s2 = derive_session_from_timestamp(bangkok_eve)
    assert s2 == "AFTERNOON"


def test_late_utc_evening_maps_to_afternoon_same_day():
    ts = datetime(2026, 8, 21, 10, 5, tzinfo=timezone.utc)  # 16:35 Yangon
    d, s = derive_session_from_timestamp(ts)
    assert s == "AFTERNOON" and str(d) == "2026-08-21"


def test_next_session_rollover_to_tomorrow():
    after_last = datetime(2026, 8, 23, 11, 0, tzinfo=timezone.utc)  # 17:30 Yangon
    d, s, cut = current_or_next_session(after_last)
    assert s == "MORNING"
    assert d == date(2026, 8, 24)  # next Yangon day
    assert cut == datetime(2026, 8, 24, 5, 30, tzinfo=timezone.utc)


def test_cutoffs_are_strictly_ordered():
    d = date(2026, 8, 25)
    assert session_cutoff_utc(d, "MORNING") < session_cutoff_utc(d, "AFTERNOON")


def test_weekend_rollover_saturday_to_monday():
    """Thai SET closed Sat/Sun: Saturday evening rolls to MONDAY morning."""
    from datetime import date, datetime, timezone

    sat_evening = datetime(2026, 8, 29, 11, 0, tzinfo=timezone.utc)  # 17:30 Yangon Sat
    d, s, cut = current_or_next_session(sat_evening)
    assert s == "MORNING" and d == date(2026, 8, 31)  # Monday
    assert cut == datetime(2026, 8, 31, 5, 30, tzinfo=timezone.utc)


def test_weekend_rollover_sunday_midday():
    from datetime import date, datetime, timezone

    sun = datetime(2026, 8, 30, 4, 0, tzinfo=timezone.utc)  # 10:30 Yangon Sunday
    d, s, cut = current_or_next_session(sun)
    assert s == "MORNING" and d == date(2026, 8, 31)


def test_next_session_date_for_skips_weekends_and_passed_cutoff():
    from datetime import date, datetime, timezone

    from prediction.timeutils import next_session_date_for

    # Monday 14:00 Yangon (08:30 UTC): MORNING cutoff passed -> Tuesday.
    mon_pm = datetime(2026, 8, 31, 8, 30, tzinfo=timezone.utc)
    assert next_session_date_for("MORNING", mon_pm) == date(2026, 9, 1)
    # AFTERNOON still ahead on Monday -> today.
    assert next_session_date_for("AFTERNOON", mon_pm) == date(2026, 8, 31)
    # Friday afternoon after cutoff -> Monday.
    fri_pm = datetime(2026, 8, 28, 11, 0, tzinfo=timezone.utc)  # 17:30 Yangon Fri
    assert next_session_date_for("MORNING", fri_pm) == date(2026, 8, 31)
