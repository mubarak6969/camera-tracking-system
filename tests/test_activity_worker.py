"""Exercises InputActivityWorker with a fake pynput-shaped listener factory
- no real global keyboard/mouse hook is installed during the automated
test suite.
"""
from __future__ import annotations

import dataclasses

from focus_tracker.core.sensor_events import ActivityEvent
from focus_tracker.input_monitor.activity_worker import InputActivityWorker


class FakeListener:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def _make_factory(captured_handler_holder: list):
    def factory(handle_raw_input):
        captured_handler_holder.append(handle_raw_input)
        return FakeListener(), FakeListener()

    return factory


def test_start_creates_and_starts_both_listeners():
    handlers: list = []
    worker = InputActivityWorker(on_activity=lambda e: None, listener_factory=_make_factory(handlers))

    worker.start()

    assert worker.is_running is True
    assert worker._keyboard_listener.started is True  # type: ignore[union-attr]
    assert worker._mouse_listener.started is True  # type: ignore[union-attr]


def test_stop_stops_both_listeners():
    handlers: list = []
    worker = InputActivityWorker(on_activity=lambda e: None, listener_factory=_make_factory(handlers))
    worker.start()
    keyboard_listener = worker._keyboard_listener
    mouse_listener = worker._mouse_listener

    worker.stop()

    assert keyboard_listener.stopped is True  # type: ignore[union-attr]
    assert mouse_listener.stopped is True  # type: ignore[union-attr]
    assert worker.is_running is False


def test_raw_input_emits_an_activity_event(fake_clock):
    handlers: list = []
    emitted: list = []
    worker = InputActivityWorker(
        on_activity=emitted.append, clock=fake_clock, listener_factory=_make_factory(handlers)
    )
    worker.start()

    handlers[0]()  # simulate a keystroke/mouse event, exactly like pynput would call it

    assert len(emitted) == 1
    assert isinstance(emitted[0], ActivityEvent)
    assert emitted[0].monotonic_timestamp == fake_clock()


def test_rapid_events_are_collapsed_into_one_per_interval(fake_clock):
    handlers: list = []
    emitted: list = []
    worker = InputActivityWorker(
        on_activity=emitted.append,
        collapse_interval_seconds=1.0,
        clock=fake_clock,
        listener_factory=_make_factory(handlers),
    )
    worker.start()
    handle = handlers[0]

    handle()
    handle()
    handle()
    assert len(emitted) == 1  # three rapid events collapsed into one

    fake_clock.advance(1.0)
    handle()
    assert len(emitted) == 2  # a new interval allows a new event through


def test_activity_event_never_carries_key_or_coordinate_data():
    field_names = {f.name for f in dataclasses.fields(ActivityEvent)}
    assert field_names == {"monotonic_timestamp"}


def test_raw_callback_ignores_whatever_arguments_pynput_passes(fake_clock):
    handlers: list = []
    emitted: list = []
    worker = InputActivityWorker(
        on_activity=emitted.append, clock=fake_clock, listener_factory=_make_factory(handlers)
    )
    worker.start()
    handle = handlers[0]

    # Mimic real pynput callback shapes: on_press(key), on_move(x, y),
    # on_click(x, y, button, pressed), on_scroll(x, y, dx, dy).
    handle("some_key")
    fake_clock.advance(2.0)
    handle(100, 200)
    fake_clock.advance(2.0)
    handle(100, 200, "Button.left", True)

    assert len(emitted) == 3
    for event in emitted:
        assert dataclasses.asdict(event) == {"monotonic_timestamp": event.monotonic_timestamp}


def test_listener_factory_failure_is_handled_without_crashing():
    def failing_factory(_handler):
        raise OSError("hook installation failed")

    errors: list = []
    worker = InputActivityWorker(
        on_activity=lambda e: None,
        listener_factory=failing_factory,
        on_error=errors.append,
    )

    worker.start()  # must not raise

    assert worker.is_running is False
    assert len(errors) == 1
    assert isinstance(errors[0], OSError)


def test_stop_before_start_is_a_no_op():
    worker = InputActivityWorker(on_activity=lambda e: None)
    worker.stop()  # must not raise
    assert worker.is_running is False
