from __future__ import annotations

import threading

import pytest

from focus_tracker.concurrency import PeriodicWorker


def test_action_is_called_repeatedly_until_stopped():
    call_count = 0
    lock = threading.Lock()
    enough_calls = threading.Event()

    def action() -> None:
        nonlocal call_count
        with lock:
            call_count += 1
            if call_count >= 3:
                enough_calls.set()

    worker = PeriodicWorker(interval_seconds=0.01, action=action, name="test-worker")
    worker.start()
    try:
        assert enough_calls.wait(timeout=2.0)
    finally:
        worker.stop()

    assert call_count >= 3
    assert worker.is_running is False


def test_exception_in_action_does_not_stop_the_loop():
    call_count = 0
    lock = threading.Lock()
    enough_calls = threading.Event()

    def flaky_action() -> None:
        nonlocal call_count
        with lock:
            call_count += 1
            count = call_count
        if count == 1:
            raise RuntimeError("boom")
        if count >= 3:
            enough_calls.set()

    worker = PeriodicWorker(interval_seconds=0.01, action=flaky_action, name="test-worker")
    worker.start()
    try:
        assert enough_calls.wait(timeout=2.0)
    finally:
        worker.stop()


def test_stop_before_start_is_a_no_op():
    worker = PeriodicWorker(interval_seconds=1.0, action=lambda: None)
    worker.stop()
    assert worker.is_running is False


def test_starting_twice_does_not_spawn_a_second_thread():
    worker = PeriodicWorker(interval_seconds=0.05, action=lambda: None)
    worker.start()
    first_thread = worker._thread
    worker.start()
    try:
        assert worker._thread is first_thread
    finally:
        worker.stop()


def test_interval_must_be_positive():
    with pytest.raises(ValueError):
        PeriodicWorker(interval_seconds=0, action=lambda: None)
