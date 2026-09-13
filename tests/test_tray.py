from __future__ import annotations

from focus_tracker.app.controller import FocusTrackerController
from focus_tracker.config.settings import AppConfig
from focus_tracker.core.sensor_events import PresenceEvent
from focus_tracker.core.states import FocusState
from focus_tracker.storage.db import Database
from focus_tracker.ui.main_window import MainWindow


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


def _make_window(qtbot, tmp_path, fake_clock):
    cameras: list[_FakeCamera] = []

    def camera_factory(**kwargs):
        cam = _FakeCamera(**kwargs)
        cameras.append(cam)
        return cam

    config = AppConfig(database_path=tmp_path / "test.db")
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


def test_tray_pause_action_pauses_the_session(qtbot, tmp_path, fake_clock):
    window, controller, cameras = _make_window(qtbot, tmp_path, fake_clock)
    try:
        cameras[0].emit_presence(True, fake_clock)

        window._tray._on_pause_resume()  # simulates clicking the tray menu's Pause action

        assert controller.get_snapshot().state is FocusState.PAUSED
    finally:
        controller.shutdown()


def test_tray_resume_action_resumes_the_session(qtbot, tmp_path, fake_clock):
    window, controller, cameras = _make_window(qtbot, tmp_path, fake_clock)
    try:
        cameras[0].emit_presence(True, fake_clock)
        controller.pause()

        window._tray._on_pause_resume()  # Pause action now behaves as Resume

        assert controller.get_snapshot().state is FocusState.WORKING
    finally:
        controller.shutdown()


def test_tray_show_action_restores_a_hidden_window(qtbot, tmp_path, fake_clock):
    window, controller, cameras = _make_window(qtbot, tmp_path, fake_clock)
    try:
        window.hide()
        assert window.isHidden() is True

        window._tray._on_show()

        assert window.isHidden() is False
    finally:
        controller.shutdown()


def test_tray_exit_action_triggers_real_exit_path(qtbot, tmp_path, fake_clock):
    window, controller, cameras = _make_window(qtbot, tmp_path, fake_clock)
    window._really_quit = False

    window._tray._on_exit()

    assert window._really_quit is True
    controller.shutdown()


def test_tray_refresh_reflects_current_state(qtbot, tmp_path, fake_clock):
    window, controller, cameras = _make_window(qtbot, tmp_path, fake_clock)
    try:
        assert window._tray._pause_action.isEnabled() is False  # not ready yet

        cameras[0].emit_presence(True, fake_clock)
        window._tray.refresh()

        assert window._tray._pause_action.isEnabled() is True
        assert window._tray._pause_action.text() == "Pause"
    finally:
        controller.shutdown()
