"""Deterministic focus state machine.

This module has no knowledge of Qt, OpenCV, pynput, or SQLite. It only
reacts to abstract signals - activity, idle, presence lost/detected, and
explicit user actions - using a caller-supplied clock function. Injecting
the clock (rather than calling time.monotonic() internally) is what makes
the 2-minute grace period fully unit-testable without a real sleep().
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from focus_tracker.core.states import FocusState, InvalidTransitionError, StateChangeEvent

Clock = Callable[[], float]

# States from which an explicit pause() is allowed.
_PAUSABLE_STATES = frozenset({FocusState.WORKING, FocusState.INACTIVE, FocusState.ALERT})


class StateMachine:
    def __init__(
        self,
        grace_period_seconds: float = 120.0,
        clock: Clock = time.monotonic,
        on_transition: Optional[Callable[[StateChangeEvent], None]] = None,
    ) -> None:
        if grace_period_seconds <= 0:
            raise ValueError("grace_period_seconds must be positive")
        self._grace_period_seconds = grace_period_seconds
        self._clock = clock
        self._on_transition = on_transition

        # A freshly created session starts WORKING: the app was just
        # launched, which itself counts as the user being present and active.
        self._state = FocusState.WORKING
        self._last_activity_at: float = self._clock()
        self._inactive_since: Optional[float] = None

    @property
    def state(self) -> FocusState:
        return self._state

    @property
    def grace_period_seconds(self) -> float:
        return self._grace_period_seconds

    # -- Passive sensor signals (idempotent - safe to call repeatedly) ----

    def record_activity(self) -> None:
        """Called whenever the (future) input monitor sees a keystroke or
        mouse event. Always safe to call, including while WORKING."""
        self._last_activity_at = self._clock()
        if self._state in (FocusState.INACTIVE, FocusState.ALERT):
            self._inactive_since = None
            self._transition(FocusState.WORKING)

    def mark_idle(self) -> None:
        """Called by the (future) input monitor once no activity has been
        seen for its idle threshold. Only has an effect from WORKING - if
        we are already INACTIVE, repeating this must NOT reset the grace
        timer, or the 2-minute window would never elapse."""
        if self._state is FocusState.WORKING:
            self._inactive_since = self._clock()
            self._transition(FocusState.INACTIVE)

    def tick(self) -> None:
        """Called periodically (e.g. once a second) to check whether the
        grace period has elapsed while INACTIVE. A no-op in every other
        state."""
        if self._state is FocusState.INACTIVE:
            assert self._inactive_since is not None
            if self._clock() - self._inactive_since >= self._grace_period_seconds:
                self._transition(FocusState.ALERT)

    def presence_lost(self) -> None:
        """Called by the (future) camera module the moment no face is
        detected. Stops the session immediately, from any state."""
        if self._state is FocusState.AWAY:
            return
        self._transition(FocusState.AWAY)

    def presence_detected(self) -> None:
        """Called by the (future) camera module when presence returns. A
        no-op unless we are currently AWAY - the camera confirms presence
        on every frame, so this must not disturb an already-active state."""
        if self._state is not FocusState.AWAY:
            return
        self._transition(self._activity_based_state())

    # -- Explicit user actions (invalid from the wrong state -> raises) ---

    def continue_working(self) -> None:
        """The user clicked "I'm still here" on the inactivity alert."""
        if self._state is not FocusState.ALERT:
            raise InvalidTransitionError(
                f"continue_working() is only valid from ALERT, current state is {self._state}"
            )
        self._last_activity_at = self._clock()
        self._inactive_since = None
        self._transition(FocusState.WORKING)

    def pause(self) -> None:
        if self._state not in _PAUSABLE_STATES:
            raise InvalidTransitionError(f"pause() is not valid from {self._state}")
        self._transition(FocusState.PAUSED)

    def resume(self) -> None:
        if self._state is not FocusState.PAUSED:
            raise InvalidTransitionError(
                f"resume() is only valid from PAUSED, current state is {self._state}"
            )
        self._transition(self._activity_based_state())

    # -- Internal helpers ---------------------------------------------------

    def _activity_based_state(self) -> FocusState:
        """Used by resume() and presence_detected(): decide whether the
        session should come back as WORKING or INACTIVE based on how long
        it has been since the last recorded activity."""
        now = self._clock()
        elapsed_since_activity = now - self._last_activity_at
        if elapsed_since_activity >= self._grace_period_seconds:
            self._inactive_since = now
            return FocusState.INACTIVE
        self._inactive_since = None
        return FocusState.WORKING

    def _transition(self, to_state: FocusState) -> None:
        from_state = self._state
        if from_state is to_state:
            return
        self._state = to_state
        if self._on_transition is not None:
            self._on_transition(
                StateChangeEvent(
                    from_state=from_state,
                    to_state=to_state,
                    monotonic_timestamp=self._clock(),
                )
            )
