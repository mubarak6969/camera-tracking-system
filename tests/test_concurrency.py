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


def test_stop_logs_a_warning_if_the_thread_does_not_join_in_time(caplog):
    release = threading.Event()

    def blocking_action() -> None:
        release.wait(timeout=5.0)  # simulates a stuck/blocking action

    worker = PeriodicWorker(interval_seconds=0.01, action=blocking_action, name="stuck-worker")
    worker.start()
    try:
        # Give the thread a moment to actually enter the blocking action.
        import time as _time

        _time.sleep(0.05)
        with caplog.at_level("WARNING"):
            worker.stop(timeout=0.2)  # much shorter than the action's own 5s wait
        assert any("did not stop within" in record.message for record in caplog.records)
    finally:
        release.set()  # let the real thread finish so it doesn't linger past the test
