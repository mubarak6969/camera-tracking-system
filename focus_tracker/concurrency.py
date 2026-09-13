"""A small reusable background-thread scheduling primitive.

Used by the camera worker (to sample frames on an interval) and by the
application wiring (to drive SensorBridge.poll() on an interval) so
neither needs to hand-roll its own thread/stop-event bookkeeping. Kept at
the top level of the package (not under core/) since it is a plain
concurrency utility, not part of the sensing-independent core logic.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class PeriodicWorker:
    """Runs `action` every `interval_seconds` on a dedicated daemon thread
    until `stop()` is called. An exception raised by `action` is logged
    and swallowed so one bad tick never kills the loop or the process."""

    def __init__(
        self,
        interval_seconds: float,
        action: Callable[[], None],
        name: str = "PeriodicWorker",
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._interval_seconds = interval_seconds
        self._action = action
        self._name = name
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=timeout)
        self._thread = None

    def _run(self) -> None:
        # wait() returns True only if the stop event was set before the
        # interval elapsed, so this both sleeps and checks for shutdown.
        while not self._stop_event.wait(self._interval_seconds):
            try:
                self._action()
            except Exception:
                logger.exception("%s: unhandled error in periodic action", self._name)
