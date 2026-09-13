"""UI-level tests using pytest-qt's qtbot against a real
FocusTrackerController wired to fake camera/input/lock workers (never
real hardware), so the signals MainWindow connects to are genuine Qt
signals, not stand-ins.
"""
from __future__ import annotations

from PySide6.QtCore import Qt

from focus_tracker.app.controller import FocusTrackerController
from focus_tracker.config.settings import AppConfig
from focus_tracker.core.sensor_events import PresenceEvent
from focus_tracker.core.states import FocusState
from focus_tracker.storage.db import Database
from focus_tracker.ui.main_window import MainWindow

GRACE = 120.0
IDLE = 5.0


class _FakeWorker:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _FakeCamera(_FakeWorker):
    def emit_presence(self, present: bool, clock) -> None:
        self.kwargs["on_presence_change"](PresenceEvent(present=present, monotonic_timestamp=clock()))

    def emit_availability(self, available: bool) -> None:
        self.kwargs["on_availability_change"](available)


def _make_window(qtbot, tmp_path, fake_clock):
    cameras: list[_FakeCamera] = []

    def camera_factory(**kwargs):
        cam = _FakeCamera(**kwargs)
        cameras.append(cam)
        return cam

    config = AppConfig(
        inactivity_grace_period_seconds=GRACE,
        activity_idle_threshold_seconds=IDLE,
        database_path=tmp_path / "test.db",
    )
    controller = FocusTrackerController(
        config,
        clock=fake_clock,
        database_factory=lambda: Database(config.database_path),
        camera_factory=camera_factory,
        input_factory=_FakeWorker,
        lock_monitor_factory=_FakeWorker,
    )
    controller.start()
    window = MainWindow(controller, config)
    qtbot.addWidget(window)
    return window, controller, cameras


def test_initial_display_shows_starting(qtbot, tmp_path, fake_clock):
    window, controller, cameras = _make_window(qtbot, tmp_path, fake_clock)
    try:
        assert "Starting" in window._status_label.text()
        assert window._pause_button.isEnabled() is False
    finally:
        controller.shutdown()


def test_display_updates_after_presence_established(qtbot, tmp_path, fake_clock):
    window, controller, cameras = _make_window(qtbot, tmp_path, fake_clock)
    try:
        cameras[0].emit_presence(True, fake_clock)
        fake_clock.advance(5)
        window._refresh()

        assert window._status_label.text() == "Working"
        assert window._timer_label.text() == "00:00:05"
        assert window._pause_button.isEnabled() is True
        assert window._pause_button.text() == "Pause"
    finally:
        controller.shutdown()


def test_pause_button_toggles_and_calls_controller(qtbot, tmp_path, fake_clock):
    window, controller, cameras = _make_window(qtbot, tmp_path, fake_clock)
    try:
        cameras[0].emit_presence(True, fake_clock)
        window._refresh()

        qtbot.mouseClick(window._pause_button, Qt.MouseButton.LeftButton)

        assert controller.get_snapshot().state is FocusState.PAUSED
        window._refresh()
        assert window._pause_button.text() == "Resume"
    finally:
        controller.shutdown()


def test_alert_dialog_shown_exactly_once_per_episode(qtbot, tmp_path, fake_clock):
    window, controller, cameras = _make_window(qtbot, tmp_path, fake_clock)
    try:
        cameras[0].emit_presence(True, fake_clock)
        fake_clock.advance(IDLE)
        controller._on_poll()
        fake_clock.advance(GRACE)
        controller._on_poll()  # enters ALERT -> alert_entered fires once

        qtbot.wait(50)  # let the queued signal reach the (same-thread here) slot
        assert window._alert_dialog is not None

        first_dialog = window._alert_dialog
        controller._on_poll()  # still ALERT - must not spawn a second dialog
        assert window._alert_dialog is first_dialog
    finally:
        controller.shutdown()


def test_dismissing_alert_dialog_without_a_choice_pauses(qtbot, tmp_path, fake_clock):
    window, controller, cameras = _make_window(qtbot, tmp_path, fake_clock)
    try:
        cameras[0].emit_presence(True, fake_clock)
        fake_clock.advance(IDLE)
        controller._on_poll()
        fake_clock.advance(GRACE)
        controller._on_poll()
        qtbot.wait(50)

        dialog = window._alert_dialog
        assert dialog is not None
        dialog.close()  # simulate the user clicking the window's X button

        assert controller.get_snapshot().state is FocusState.PAUSED
    finally:
        controller.shutdown()


def test_continue_clears_alert_and_resumes_working(qtbot, tmp_path, fake_clock):
    window, controller, cameras = _make_window(qtbot, tmp_path, fake_clock)
    try:
        cameras[0].emit_presence(True, fake_clock)
        fake_clock.advance(IDLE)
        controller._on_poll()
        fake_clock.advance(GRACE)
        controller._on_poll()
        qtbot.wait(50)

        window._alert_dialog.continue_clicked.emit()

        assert controller.get_snapshot().state is FocusState.WORKING
        assert window._alert_dialog is None
    finally:
        controller.shutdown()


def test_error_banner_shown_and_cleared_on_camera_recovery(qtbot, tmp_path, fake_clock):
    window, controller, cameras = _make_window(qtbot, tmp_path, fake_clock)
    try:
        window.show()  # isVisible() below is only meaningful once the window is actually shown
        qtbot.waitExposed(window)
        cameras[0].emit_availability(False)
        qtbot.wait(50)
        assert window._banner_label.isVisible() is True

        cameras[0].emit_availability(True)
        qtbot.wait(50)
        assert window._banner_label.isVisible() is False
    finally:
        controller.shutdown()


def test_close_event_hides_instead_of_closing_the_process(qtbot, tmp_path, fake_clock):
    window, controller, cameras = _make_window(qtbot, tmp_path, fake_clock)
    try:
        window.show()
        window.close()
        assert window.isHidden() is True
        assert window._really_quit is False
    finally:
        controller.shutdown()


def test_tray_icon_created(qtbot, tmp_path, fake_clock):
    window, controller, cameras = _make_window(qtbot, tmp_path, fake_clock)
    try:
        assert window._tray.tray_icon is not None
    finally:
        controller.shutdown()
