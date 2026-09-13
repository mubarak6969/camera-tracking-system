"""Elapsed active-work-time accounting.

The timer has no idea what a "state" is; it only knows whether counting
is currently on or off, and is driven by FocusSession. Every method is
idempotent so that repeated identical signals (e.g. the camera confirming
presence on every single frame) never corrupt the accumulated total. Time
is always computed from monotonic timestamp differences, never by
incrementing a counter once a second, so accuracy does not depend on how
often the timer is polled.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

Clock = Callable[[], float]


class TimerStateError(RuntimeError):
    """Raised when a timer method is called in an order that makes no sense
    (e.g. pausing before start(), or starting twice)."""


class SessionTimer:
    def __init__(self, clock: Clock = time.monotonic) -> None:
        self._clock = clock
        self._accumulated_seconds: float = 0.0
        self._segment_start: Optional[float] = None
        self._started = False
        self._ended = False

    def start(self) -> None:
        if self._started:
            raise TimerStateError("start() may only be called once per SessionTimer")
        self._started = True
        self._segment_start = self._clock()

    def pause(self) -> None:
        self._require_started()
        self._close_segment()

    def resume(self) -> None:
        self._require_started()
        if self._ended:
            raise TimerStateError("cannot resume a timer that has already ended")
        if self._segment_start is None:
            self._segment_start = self._clock()
        # else: already counting - idempotent no-op, do not reset the segment.

    def mark_away(self) -> None:
        self.pause()

    def mark_present(self) -> None:
        self.resume()

    def end(self) -> float:
        self._require_started()
        self._close_segment()
        self._ended = True
        return self._accumulated_seconds

    def elapsed(self) -> float:
        if self._segment_start is None:
            return self._accumulated_seconds
        return self._accumulated_seconds + (self._clock() - self._segment_start)

    def _close_segment(self) -> None:
        if self._segment_start is not None:
            self._accumulated_seconds += self._clock() - self._segment_start
            self._segment_start = None

    def _require_started(self) -> None:
        if not self._started:
            raise TimerStateError("timer has not been started yet")
