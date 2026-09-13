from __future__ import annotations

import pytest

from focus_tracker.core.state_machine import StateMachine
from focus_tracker.core.states import FocusState, InvalidTransitionError

GRACE = 120.0


def make_sm(clock) -> StateMachine:
    return StateMachine(grace_period_seconds=GRACE, clock=clock)


def test_initial_state_is_working(fake_clock):
    sm = make_sm(fake_clock)
    assert sm.state is FocusState.WORKING


def test_working_to_inactive(fake_clock):
    sm = make_sm(fake_clock)
    sm.mark_idle()
    assert sm.state is FocusState.INACTIVE


def test_inactive_to_working_on_activity(fake_clock):
    sm = make_sm(fake_clock)
    sm.mark_idle()
    sm.record_activity()
    assert sm.state is FocusState.WORKING


def test_inactive_to_alert_after_grace_period(fake_clock):
    sm = make_sm(fake_clock)
    sm.mark_idle()
    fake_clock.advance(GRACE)
    sm.tick()
    assert sm.state is FocusState.ALERT


def test_inactive_stays_inactive_before_grace_period_elapses(fake_clock):
    sm = make_sm(fake_clock)
    sm.mark_idle()
    fake_clock.advance(GRACE - 1)
    sm.tick()
    assert sm.state is FocusState.INACTIVE


def test_exact_grace_period_boundary(fake_clock):
    sm = make_sm(fake_clock)
    sm.mark_idle()
    fake_clock.advance(GRACE - 0.001)
    sm.tick()
    assert sm.state is FocusState.INACTIVE  # not yet - just under the boundary
    fake_clock.advance(0.001)
    sm.tick()
    assert sm.state is FocusState.ALERT  # exactly at the boundary


def test_alert_to_working_via_continue(fake_clock):
    sm = make_sm(fake_clock)
    sm.mark_idle()
    fake_clock.advance(GRACE)
    sm.tick()
    sm.continue_working()
    assert sm.state is FocusState.WORKING


def test_alert_to_working_via_activity(fake_clock):
    sm = make_sm(fake_clock)
    sm.mark_idle()
    fake_clock.advance(GRACE)
    sm.tick()
    sm.record_activity()
    assert sm.state is FocusState.WORKING


def test_alert_to_paused(fake_clock):
    sm = make_sm(fake_clock)
    sm.mark_idle()
    fake_clock.advance(GRACE)
    sm.tick()
    sm.pause()
    assert sm.state is FocusState.PAUSED


def test_working_to_away(fake_clock):
    sm = make_sm(fake_clock)
    sm.presence_lost()
    assert sm.state is FocusState.AWAY


def test_inactive_to_away(fake_clock):
    sm = make_sm(fake_clock)
    sm.mark_idle()
    sm.presence_lost()
    assert sm.state is FocusState.AWAY


def test_alert_to_away(fake_clock):
    sm = make_sm(fake_clock)
    sm.mark_idle()
    fake_clock.advance(GRACE)
    sm.tick()
    sm.presence_lost()
    assert sm.state is FocusState.AWAY


def test_away_to_working_when_activity_is_recent(fake_clock):
    sm = make_sm(fake_clock)
    sm.presence_lost()
    fake_clock.advance(5)
    sm.presence_detected()
    assert sm.state is FocusState.WORKING


def test_away_to_inactive_when_activity_is_stale(fake_clock):
    sm = make_sm(fake_clock)
    sm.presence_lost()
    fake_clock.advance(GRACE + 10)
    sm.presence_detected()
    assert sm.state is FocusState.INACTIVE


def test_paused_resume_to_working(fake_clock):
    sm = make_sm(fake_clock)
    sm.pause()
    fake_clock.advance(5)
    sm.resume()
    assert sm.state is FocusState.WORKING


def test_paused_resume_to_inactive_when_activity_is_stale(fake_clock):
    sm = make_sm(fake_clock)
    sm.pause()
    fake_clock.advance(GRACE + 10)
    sm.resume()
    assert sm.state is FocusState.INACTIVE


def test_custom_grace_period_is_respected(fake_clock):
    sm = StateMachine(grace_period_seconds=5.0, clock=fake_clock)
    sm.mark_idle()
    fake_clock.advance(5.0)
    sm.tick()
    assert sm.state is FocusState.ALERT


@pytest.mark.parametrize(
    "setup, action",
    [
        (lambda sm: None, lambda sm: sm.resume()),  # resume while WORKING
        (lambda sm: None, lambda sm: sm.continue_working()),  # continue while WORKING
        (lambda sm: sm.mark_idle(), lambda sm: sm.continue_working()),  # continue while INACTIVE
        (lambda sm: sm.presence_lost(), lambda sm: sm.pause()),  # pause while AWAY
        (lambda sm: sm.pause(), lambda sm: sm.pause()),  # pause while already PAUSED
        (lambda sm: sm.pause(), lambda sm: sm.continue_working()),  # continue while PAUSED
        (lambda sm: sm.presence_lost(), lambda sm: sm.resume()),  # resume while AWAY
    ],
)
def test_invalid_transitions_raise(fake_clock, setup, action):
    sm = make_sm(fake_clock)
    setup(sm)
    with pytest.raises(InvalidTransitionError):
        action(sm)


def test_repeated_idle_signals_do_not_reset_grace_timer(fake_clock):
    sm = make_sm(fake_clock)
    sm.mark_idle()
    fake_clock.advance(GRACE - 1)
    sm.mark_idle()  # repeated signal - must not reset the inactivity clock
    fake_clock.advance(1)
    sm.tick()
    assert sm.state is FocusState.ALERT


def test_repeated_presence_detected_while_active_is_a_no_op(fake_clock):
    sm = make_sm(fake_clock)
    sm.presence_detected()  # already WORKING - must be a harmless no-op
    assert sm.state is FocusState.WORKING


def test_repeated_presence_lost_is_idempotent(fake_clock):
    sm = make_sm(fake_clock)
    sm.presence_lost()
    sm.presence_lost()
    assert sm.state is FocusState.AWAY


def test_grace_period_must_be_positive(fake_clock):
    with pytest.raises(ValueError):
        StateMachine(grace_period_seconds=0, clock=fake_clock)
