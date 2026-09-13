"""Background keyboard/mouse activity worker.

Wraps pynput's global keyboard and mouse listeners (each of which already
runs its own OS-hook thread - nothing here touches the UI thread) and
collapses their raw callbacks into, at most, one ActivityEvent per
`collapse_interval_seconds`. No key, character, button, or coordinate
ever leaves the private `_handle_raw_input` method - every pynput
callback signature is accepted and immediately discarded, only "something
happened, at this monotonic time" survives.

pynput's global hooks on Windows use SetWindowsHookEx, which works from a
normal user session - no administrator privileges are required.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional, Protocol, Tuple

from focus_tracker.core.sensor_events import ActivityEvent
from focus_tracker.core.state_machine import Clock

logger = logging.getLogger(__name__)


class _Listener(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


ListenerFactory = Callable[[Callable[..., None]], Tuple[_Listener, _Listener]]


def _default_listener_factory(handle_raw_input: Callable[..., None]) -> Tuple[_Listener, _Listener]:
    from pynput import keyboard, mouse

    keyboard_listener = keyboard.Listener(
        on_press=lambda key: handle_raw_input(),
        on_release=lambda key: handle_raw_input(),
    )
    mouse_listener = mouse.Listener(
        on_move=lambda x, y: handle_raw_input(),
        on_click=lambda x, y, button, pressed: handle_raw_input(),
        on_scroll=lambda x, y, dx, dy: handle_raw_input(),
    )
    return keyboard_listener, mouse_listener


class InputActivityWorker:
    def __init__(
        self,
        on_activity: Callable[[ActivityEvent], None],
        collapse_interval_seconds: float = 1.0,
        clock: Clock = time.monotonic,
        listener_factory: ListenerFactory = _default_listener_factory,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        self._on_activity = on_activity
        self._collapse_interval_seconds = collapse_interval_seconds
        self._clock = clock
        self._listener_factory = listener_factory
        self._on_error = on_error

        self._lock = threading.Lock()
        self._last_emitted_at: Optional[float] = None
        self._keyboard_listener: Optional[_Listener] = None
        self._mouse_listener: Optional[_Listener] = None

    @property
    def is_running(self) -> bool:
        return self._keyboard_listener is not None and self._mouse_listener is not None

    def start(self) -> None:
        if self.is_running:
            return
        try:
            keyboard_listener, mouse_listener = self._listener_factory(self._handle_raw_input)
            keyboard_listener.start()
            mouse_listener.start()
        except Exception as exc:
            logger.exception("InputActivityWorker: failed to start listeners")
            if self._on_error is not None:
                self._on_error(exc)
            return
        self._keyboard_listener = keyboard_listener
        self._mouse_listener = mouse_listener

    def stop(self) -> None:
        for listener in (self._keyboard_listener, self._mouse_listener):
            if listener is None:
                continue
            try:
                listener.stop()
            except Exception:
                logger.exception("InputActivityWorker: error stopping a listener")
        self._keyboard_listener = None
        self._mouse_listener = None

    def _handle_raw_input(self, *_args: Any, **_kwargs: Any) -> None:
        # Every argument pynput might pass (key, coordinates, button,
        # scroll delta, ...) is accepted above only to satisfy the
        # callback signature, then ignored here - nothing but a
        # timestamp is ever derived from it.
        try:
            with self._lock:
                now = self._clock()
                if (
                    self._last_emitted_at is not None
                    and (now - self._last_emitted_at) < self._collapse_interval_seconds
                ):
                    return
                self._last_emitted_at = now
            self._on_activity(ActivityEvent(monotonic_timestamp=now))
        except Exception:
            # A crash inside this callback would otherwise propagate into
            # pynput's internal hook thread and could take the listener
            # down silently.
            logger.exception("InputActivityWorker: error handling an input event")
