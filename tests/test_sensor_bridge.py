"""Integration tests: real sensor event types feeding into the existing,
unmodified FocusSession/StateMachine/SessionTimer - proving the new
sensing layer connects to core through its existing public API only.
"""
from __future__ import annotations

import pytest

from focus_tracker.core.lock_events import SessionLockEvent, SessionLockEventKind
from focus_tracker.core.sensor_bridge import SensorBridge
from focus_tracker.core.sensor_events import ActivityEvent, PresenceEvent
from focus_tracker.core.session import FocusSession
from focus_tracker.core.states import FocusState

GRACE = 120.0
IDLE_THRESHOLD = 5.0


def _make(fake_clock):
    session = FocusSession(grace_period_seconds=GRACE, clock=fake_clock)
    session.start()
    bridge = SensorBridge(session, idle_threshold_seconds=IDLE_THRESHOLD, clock=fake_clock)
    return session, bridge


def test_presence_loss_moves_to_away_immediately(fake_clock):
    session, bridge = _make(fake_clock)

    bridge.handle_presence(PresenceEvent(present=False, monotonic_timestamp=fake_clock()))

    assert session.state is FocusState.AWAY


def test_presence_return_resumes_working_when_activity_is_recent(fake_clock):
    session, bridge = _make(fake_clock)
    bridge.handle_activity(ActivityEvent(monotonic_timestamp=fake_clock()))
    bridge.handle_presence(PresenceEvent(present=False, monotonic_timestamp=fake_clock()))
    fake_clock.advance(5)

    bridge.handle_presence(PresenceEvent(present=True, monotonic_timestamp=fake_clock()))

    assert session.state is FocusState.WORKING


def test_presence_return_resumes_inactive_when_activity_is_stale(fake_clock):
    session, bridge = _make(fake_clock)
    bridge.handle_presence(PresenceEvent(present=False, monotonic_timestamp=fake_clock()))
    fake_clock.advance(GRACE + 30)

    bridge.handle_presence(PresenceEvent(present=True, monotonic_timestamp=fake_clock()))

    assert session.state is FocusState.INACTIVE


def test_inactivity_reaches_alert_via_poll(fake_clock):
    session, bridge = _make(fake_clock)
    bridge.handle_activity(ActivityEvent(monotonic_timestamp=fake_clock()))

    fake_clock.advance(IDLE_THRESHOLD)
    bridge.poll()  # no activity for idle_threshold -> WORKING to INACTIVE
    assert session.state is FocusState.INACTIVE

    fake_clock.advance(GRACE)
    bridge.poll()  # inactive for the full grace period -> ALERT
    assert session.state is FocusState.ALERT


def test_activity_resets_inactivity(fake_clock):
    session, bridge = _make(fake_clock)
    bridge.handle_activity(ActivityEvent(monotonic_timestamp=fake_clock()))
    fake_clock.advance(IDLE_THRESHOLD)
    bridge.poll()
    assert session.state is FocusState.INACTIVE

    bridge.handle_activity(ActivityEvent(monotonic_timestamp=fake_clock()))
    assert session.state is FocusState.WORKING

    fake_clock.advance(IDLE_THRESHOLD - 0.1)
    bridge.poll()
    assert session.state is FocusState.WORKING  # the reset actually took effect


def test_repeated_presence_events_do_not_corrupt_elapsed_time(fake_clock):
    session, bridge = _make(fake_clock)
    fake_clock.advance(10)
    bridge.handle_presence(PresenceEvent(present=False, monotonic_timestamp=fake_clock()))
    bridge.handle_presence(PresenceEvent(present=False, monotonic_timestamp=fake_clock()))
    bridge.handle_presence(PresenceEvent(present=False, monotonic_timestamp=fake_clock()))
    fake_clock.advance(100)  # away time - must not count, no matter how many repeats above
    bridge.handle_presence(PresenceEvent(present=True, monotonic_timestamp=fake_clock()))
    bridge.handle_presence(PresenceEvent(present=True, monotonic_timestamp=fake_clock()))
    fake_clock.advance(5)

    assert session.elapsed_work_time == pytest.approx(15)


def test_does_not_create_a_duplicate_session_on_presence_flap(fake_clock):
    session, bridge = _make(fake_clock)
    fake_clock.advance(10)
    bridge.handle_presence(PresenceEvent(present=False, monotonic_timestamp=fake_clock()))
    fake_clock.advance(2)
    bridge.handle_presence(PresenceEvent(present=True, monotonic_timestamp=fake_clock()))
    fake_clock.advance(10)

    # Same FocusSession object throughout - no new session was constructed
    # merely because presence flickered away and back.
    assert session.state in (FocusState.WORKING, FocusState.INACTIVE)
    assert session.elapsed_work_time == pytest.approx(20)


def test_lock_event_pauses_an_active_session(fake_clock):
    session, bridge = _make(fake_clock)
    fake_clock.advance(10)

    bridge.handle_lock_event(SessionLockEvent(kind=SessionLockEventKind.LOCKED, monotonic_timestamp=fake_clock()))

    assert session.state is FocusState.PAUSED
    fake_clock.advance(500)
    assert session.elapsed_work_time == pytest.approx(10)  # locked time excluded


def test_unlock_forces_away_instead_of_trusting_stale_presence(fake_clock):
    session, bridge = _make(fake_clock)
    bridge.handle_lock_event(SessionLockEvent(kind=SessionLockEventKind.LOCKED, monotonic_timestamp=fake_clock()))
    fake_clock.advance(60)

    bridge.handle_lock_event(SessionLockEvent(kind=SessionLockEventKind.UNLOCKED, monotonic_timestamp=fake_clock()))

    assert session.state is FocusState.AWAY  # not blindly resumed to WORKING

    # only a fresh PresenceEvent from the camera brings it back
    bridge.handle_presence(PresenceEvent(present=True, monotonic_timestamp=fake_clock()))
    assert session.state is FocusState.WORKING


def test_sleep_and_wake_behave_like_lock_and_unlock(fake_clock):
    session, bridge = _make(fake_clock)
    bridge.handle_lock_event(SessionLockEvent(kind=SessionLockEventKind.SLEEP, monotonic_timestamp=fake_clock()))
    assert session.state is FocusState.PAUSED

    bridge.handle_lock_event(SessionLockEvent(kind=SessionLockEventKind.WAKE, monotonic_timestamp=fake_clock()))
    assert session.state is FocusState.AWAY


def test_manual_pause_is_not_disturbed_by_an_unlock_event(fake_clock):
    session, bridge = _make(fake_clock)
    session.pause()  # the user explicitly paused - not triggered by the bridge

    bridge.handle_lock_event(SessionLockEvent(kind=SessionLockEventKind.UNLOCKED, monotonic_timestamp=fake_clock()))

    # The bridge must not resume/disturb a pause it did not itself cause.
    assert session.state is FocusState.PAUSED


def test_lock_event_while_already_away_is_a_no_op(fake_clock):
    session, bridge = _make(fake_clock)
    bridge.handle_presence(PresenceEvent(present=False, monotonic_timestamp=fake_clock()))
    assert session.state is FocusState.AWAY

    bridge.handle_lock_event(SessionLockEvent(kind=SessionLockEventKind.LOCKED, monotonic_timestamp=fake_clock()))

    assert session.state is FocusState.AWAY  # unchanged - pause() would have raised otherwise


def test_idle_threshold_must_be_positive(fake_clock):
    session = FocusSession(clock=fake_clock)
    with pytest.raises(ValueError):
        SensorBridge(session, idle_threshold_seconds=0, clock=fake_clock)
