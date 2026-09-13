"""local_midnight_utc is tested across simulated timezones by passing a
timezone-aware `reference` directly - never by changing this machine's
actual system timezone.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from focus_tracker.timeutil import local_midnight_utc


def test_utc_reference_midnight_is_unchanged():
    reference = datetime(2026, 3, 15, 23, 30, tzinfo=timezone.utc)
    result = local_midnight_utc(reference)
    assert result == datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)


def test_positive_offset_timezone_crosses_a_utc_day_boundary():
    # UTC+9 (e.g. Tokyo): local 2026-03-16 08:30 is still 2026-03-15 UTC.
    tz = timezone(timedelta(hours=9))
    reference = datetime(2026, 3, 16, 8, 30, tzinfo=tz)
    result = local_midnight_utc(reference)
    # Local midnight (2026-03-16 00:00 +09:00) is 2026-03-15 15:00 UTC.
    assert result == datetime(2026, 3, 15, 15, 0, tzinfo=timezone.utc)


def test_negative_offset_timezone_crosses_a_utc_day_boundary():
    # UTC-8 (e.g. US Pacific): local 2026-03-15 20:00 is 2026-03-16 04:00 UTC.
    tz = timezone(timedelta(hours=-8))
    reference = datetime(2026, 3, 15, 20, 0, tzinfo=tz)
    result = local_midnight_utc(reference)
    # Local midnight (2026-03-15 00:00 -08:00) is 2026-03-15 08:00 UTC.
    assert result == datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)


def test_just_before_and_after_local_midnight_land_in_different_days():
    tz = timezone(timedelta(hours=-8))
    just_before = datetime(2026, 3, 15, 23, 59, 59, tzinfo=tz)
    just_after = datetime(2026, 3, 16, 0, 0, 1, tzinfo=tz)

    assert local_midnight_utc(just_before) == datetime(2026, 3, 15, 8, 0, tzinfo=timezone.utc)
    assert local_midnight_utc(just_after) == datetime(2026, 3, 16, 8, 0, tzinfo=timezone.utc)


def test_naive_reference_is_treated_as_system_local_time():
    naive = datetime(2026, 3, 15, 12, 0)
    result = local_midnight_utc(naive)
    # Whatever this machine's timezone is, the result must be midnight in
    # that same timezone, expressed in UTC.
    expected_local_midnight = naive.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    assert result == expected_local_midnight.astimezone(timezone.utc)


def test_no_reference_defaults_to_now_and_returns_a_utc_aware_datetime():
    result = local_midnight_utc()
    assert result.tzinfo is not None
    assert result.utcoffset() == timedelta(0)
