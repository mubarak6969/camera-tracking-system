"""Bridges sensor events into FocusSession calls.

This is the one place that decides "no activity for the configured idle
threshold means INACTIVE" - a decision that belongs here, not in the pure
StateMachine (which has no notion of an idle threshold or a periodic
poll, only the grace-period boundary) and not in the camera/input workers
(which only know about frames and pynput events, not FocusSession).

SensorBridge depends only on FocusSession and the event dataclasses in
sensor_events.py / lock_events.py - never on OpenCV, pynput, or any
Windows API - so it stays fully unit-testable with fakes, and none of the
existing core/state_machine.py, core/session.py, or core/timer.py needed
to change to support real sensors.
"""
from __future__ import annotations

import time

from focus_tracker.core.lock_events import SessionLockEvent, SessionLockEventKind
from focus_tracker.core.session import FocusSession
from focus_tracker.core.sensor_events import ActivityEvent, PresenceEvent
from focus_tracker.core.state_machine import Clock
from focus_tracker.core.states import FocusState

_LOCK_KINDS = frozenset({SessionLockEventKind.LOCKED, SessionLockEventKind.SLEEP})
_UNLOCK_KINDS = frozenset({SessionLockEventKind.UNLOCKED, SessionLockEventKind.WAKE})
_PAUSABLE_STATES = frozenset({FocusState.WORKING, FocusState.INACTIVE, FocusState.ALERT})


class SensorBridge:
    def __init__(
        self,
        session: FocusSession,
        idle_threshold_seconds: float,
        clock: Clock = time.monotonic,
    ) -> None:
        if idle_threshold_seconds <= 0:
            raise ValueError("idle_threshold_seconds must be positive")
        self._session = session
        self._idle_threshold_seconds = idle_threshold_seconds
        self._clock = clock
        self._last_activity_at = self._clock()
        # True only while the session is PAUSED *because we locked it*, so
        # unlock/wake never disturbs a session the user paused themselves.
        self._auto_paused_for_lock = False

    def handle_presence(self, event: PresenceEvent) -> None:
        if event.present:
            self._session.presence_detected()
        else:
            if self._session.state is FocusState.PAUSED:
                # A manually paused session must stay paused regardless of
                # what the camera sees - only an explicit resume() (or the
                # lock-monitor's own forced-AWAY path below, for a lock/sleep
                # induced pause) may move it out of PAUSED. Without this
                # guard, presence_lost() (which core still allows from any
                # non-AWAY state, including PAUSED) would silently overwrite
                # a deliberate user pause with AWAY.
                return
            self._session.presence_lost()

    def handle_activity(self, event: ActivityEvent) -> None:
        self._last_activity_at = event.monotonic_timestamp
        self._session.record_activity()

    def poll(self) -> None:
        """Call periodically (e.g. once a second) from a background
        scheduler such as concurrency.PeriodicWorker. Detects idle time
        passing and advances the grace-period clock. Safe to call in any
        state - both calls are no-ops unless they apply."""
        now = self._clock()
        if now - self._last_activity_at >= self._idle_threshold_seconds:
            self._session.mark_idle()
        self._session.tick()

    def handle_lock_event(self, event: SessionLockEvent) -> None:
        """The machine locking or sleeping must stop the timer immediately,
        and unlocking/waking must never blindly resume - it must wait for a
        fresh presence reading rather than trusting whatever the camera
        reported before the lock."""
        if event.kind in _LOCK_KINDS:
            if self._session.state in _PAUSABLE_STATES:
                self._session.pause()
                self._auto_paused_for_lock = True
        elif event.kind in _UNLOCK_KINDS:
            if self._auto_paused_for_lock and self._session.state is FocusState.PAUSED:
                self._auto_paused_for_lock = False
                # presence_lost() is valid from PAUSED and moves to AWAY -
                # the next real PresenceEvent from the camera worker is what
                # actually brings the session back, per the normal rules.
                self._session.presence_lost()
