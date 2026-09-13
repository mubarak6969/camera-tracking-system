"""Automated coverage for WindowsSessionMonitor is deliberately limited to
its start/stop lifecycle - creating and tearing down the hidden window and
its message pump for real, without touching a physical webcam or real
keyboard/mouse hooks. It does NOT simulate an actual Windows lock, sleep,
or wake, since that would require physically locking/suspending the
machine running the test - see the manual hardware smoke test for that.
"""
from __future__ import annotations

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only component")

from focus_tracker.platform_win.session_monitor import WindowsSessionMonitor


def test_start_and_stop_does_not_raise_or_hang():
    events: list = []
    monitor = WindowsSessionMonitor(on_event=events.append)

    monitor.start()
    try:
        assert monitor._hwnd is not None
    finally:
        monitor.stop()

    assert monitor._thread is None


def test_stop_before_start_is_a_no_op():
    monitor = WindowsSessionMonitor(on_event=lambda e: None)
    monitor.stop()  # must not raise


def test_stop_is_idempotent():
    monitor = WindowsSessionMonitor(on_event=lambda e: None)
    monitor.start()
    monitor.stop()
    monitor.stop()  # calling stop again after already stopped must not raise
