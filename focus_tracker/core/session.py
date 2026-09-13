"""Wires the state machine and the work timer together.

FocusSession is the single object the rest of the app (eventually the UI,
the camera worker, and the input-monitor worker) talks to. It has no
knowledge of Qt, OpenCV, pynput, or SQLite - callers drive it through its
methods and, optionally, receive persisted-transition events through
`on_state_change` to forward to storage/repository.py themselves. This
keeps the persistence layer independent of core, as required.

The only place time accounting could accidentally double-count is at the
WORKING/INACTIVE/ALERT boundaries - so this class deliberately does
nothing to the timer on those transitions. The timer only starts/stops on
the PAUSED and AWAY boundaries, where work time must stop or resume.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from focus_tracker.core.state_machine import Clock, StateMachine
from focus_tracker.core.states import FocusState, StateChangeEvent
from focus_tracker.core.timer import SessionTimer


@dataclass(frozen=True)
class PersistableTransition:
    """A state transition paired with a wall-clock UTC timestamp, ready for
    the storage layer. The state machine itself only ever deals in
    monotonic timestamps; this is where the two are bridged."""

    from_state: FocusState
    to_state: FocusState
    occurred_at_utc: datetime


class FocusSession:
    def __init__(
        self,
        grace_period_seconds: float = 120.0,
        clock: Clock = time.monotonic,
        on_state_change: Optional[Callable[[PersistableTransition], None]] = None,
    ) -> None:
        self._on_state_change = on_state_change
        self._timer = SessionTimer(clock=clock)
        self._state_machine = StateMachine(
            grace_period_seconds=grace_period_seconds,
            clock=clock,
            on_transition=self._handle_transition,
        )

    @property
    def state(self) -> FocusState:
        return self._state_machine.state

    @property
    def elapsed_work_time(self) -> float:
        return self._timer.elapsed()

    def start(self) -> None:
        self._timer.start()

    def record_activity(self) -> None:
        self._state_machine.record_activity()

    def mark_idle(self) -> None:
        self._state_machine.mark_idle()

    def tick(self) -> None:
        self._state_machine.tick()

    def continue_working(self) -> None:
        self._state_machine.continue_working()

    def pause(self) -> None:
        self._state_machine.pause()

    def resume(self) -> None:
        self._state_machine.resume()

    def presence_lost(self) -> None:
        self._state_machine.presence_lost()

    def presence_detected(self) -> None:
        self._state_machine.presence_detected()

    def end(self) -> float:
        return self._timer.end()

    def _handle_transition(self, event: StateChangeEvent) -> None:
        if event.to_state is FocusState.AWAY:
            self._timer.mark_away()
        elif event.to_state is FocusState.PAUSED:
            self._timer.pause()
        elif event.from_state is FocusState.AWAY:
            self._timer.mark_present()
        elif event.from_state is FocusState.PAUSED:
            self._timer.resume()

        if self._on_state_change is not None:
            self._on_state_change(
                PersistableTransition(
                    from_state=event.from_state,
                    to_state=event.to_state,
                    occurred_at_utc=datetime.now(timezone.utc),
                )
            )
