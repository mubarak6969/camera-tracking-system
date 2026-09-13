from __future__ import annotations

import pytest

from focus_tracker.core.session import FocusSession
from focus_tracker.core.states import FocusState

GRACE = 120.0


def test_work_time_accumulates_across_working_inactive_alert_without_double_counting(fake_clock):
    session = FocusSession(grace_period_seconds=GRACE, clock=fake_clock)
    session.start()
    fake_clock.advance(30)  # WORKING
    session.mark_idle()  # -> INACTIVE, grace period starts
    fake_clock.advance(GRACE)
    session.tick()  # -> ALERT
    fake_clock.advance(10)
    assert session.state is FocusState.ALERT
    assert session.elapsed_work_time == pytest.approx(30 + GRACE + 10)


def test_away_time_is_excluded(fake_clock):
    session = FocusSession(grace_period_seconds=GRACE, clock=fake_clock)
    session.start()
    fake_clock.advance(30)
    session.presence_lost()
    fake_clock.advance(500)  # away - must not count
    session.presence_detected()
    fake_clock.advance(20)
    assert session.elapsed_work_time == pytest.approx(50)


def test_paused_time_is_excluded(fake_clock):
    session = FocusSession(grace_period_seconds=GRACE, clock=fake_clock)
    session.start()
    fake_clock.advance(15)
    session.pause()
    fake_clock.advance(300)  # paused - must not count
    session.resume()
    fake_clock.advance(5)
    assert session.elapsed_work_time == pytest.approx(20)


def test_repeated_state_signals_do_not_corrupt_elapsed_time(fake_clock):
    session = FocusSession(grace_period_seconds=GRACE, clock=fake_clock)
    session.start()
    fake_clock.advance(10)
    session.mark_idle()
    session.mark_idle()  # repeated
    session.mark_idle()  # repeated
    fake_clock.advance(10)
    session.record_activity()
    session.record_activity()  # repeated
    fake_clock.advance(10)
    assert session.elapsed_work_time == pytest.approx(30)


def test_on_state_change_callback_receives_persistable_transitions(fake_clock):
    events = []
    session = FocusSession(
        grace_period_seconds=GRACE, clock=fake_clock, on_state_change=events.append
    )
    session.start()
    session.mark_idle()
    session.presence_lost()

    assert [(e.from_state, e.to_state) for e in events] == [
        (FocusState.WORKING, FocusState.INACTIVE),
        (FocusState.INACTIVE, FocusState.AWAY),
    ]
    assert all(e.occurred_at_utc.tzinfo is not None for e in events)


def test_end_returns_final_accumulated_total(fake_clock):
    session = FocusSession(grace_period_seconds=GRACE, clock=fake_clock)
    session.start()
    fake_clock.advance(45)
    total = session.end()
    assert total == pytest.approx(45)
