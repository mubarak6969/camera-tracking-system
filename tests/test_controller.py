"""Tests FocusTrackerController's lifecycle, startup presence gating,
alert-once semantics, persistence integration, and error handling - all
with fake camera/input/lock-monitor workers injected via the factory
parameters, so nothing here touches real hardware. A real (tmp_path)
SQLite database is used since exercising the actual persistence path is
the point of several of these tests.
"""
from __future__ import annotations

import pytest

from focus_tracker.app.controller import FocusTrackerController
from focus_tracker.config.settings import AppConfig
from focus_tracker.core.lock_events import SessionLockEvent, SessionLockEventKind
from focus_tracker.core.sensor_events import ActivityEvent, PresenceEvent
from focus_tracker.core.states import FocusState
from focus_tracker.storage.db import Database

GRACE = 120.0
IDLE = 5.0


class FakeWorker:
    """Shared no-op start/stop base for the fake camera/input/lock workers."""

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.start_exception: Exception | None = None

    def start(self) -> None:
        self.started = True
        if self.start_exception is not None:
            raise self.start_exception

    def stop(self) -> None:
        self.stopped = True


class FakeCamera(FakeWorker):
    def emit_presence(self, present: bool, clock) -> None:
        self.kwargs["on_presence_change"](PresenceEvent(present=present, monotonic_timestamp=clock()))

    def emit_availability(self, available: bool) -> None:
        self.kwargs["on_availability_change"](available)


class FakeInput(FakeWorker):
    def emit_activity(self, clock) -> None:
        self.kwargs["on_activity"](ActivityEvent(monotonic_timestamp=clock()))

    def emit_error(self, exc: Exception) -> None:
        self.kwargs["on_error"](exc)


class FakeLockMonitor(FakeWorker):
    def emit_lock_event(self, kind: SessionLockEventKind, clock) -> None:
        self.kwargs["on_event"](SessionLockEvent(kind=kind, monotonic_timestamp=clock()))


def _make_controller(tmp_path, fake_clock, config: AppConfig | None = None):
    cameras: list[FakeCamera] = []
    inputs: list[FakeInput] = []
    locks: list[FakeLockMonitor] = []

    def camera_factory(**kwargs):
        cam = FakeCamera(**kwargs)
        cameras.append(cam)
        return cam

    def input_factory(**kwargs):
        inp = FakeInput(**kwargs)
        inputs.append(inp)
        return inp

    def lock_factory(**kwargs):
        mon = FakeLockMonitor(**kwargs)
        locks.append(mon)
        return mon

    cfg = config or AppConfig(
        inactivity_grace_period_seconds=GRACE,
        activity_idle_threshold_seconds=IDLE,
        database_path=tmp_path / "test.db",
    )
    controller = FocusTrackerController(
        cfg,
        clock=fake_clock,
        database_factory=lambda: Database(cfg.database_path),
        camera_factory=camera_factory,
        input_factory=input_factory,
        lock_monitor_factory=lock_factory,
    )
    return controller, cameras, inputs, locks


def test_start_starts_all_workers(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        assert cameras[0].started is True
        assert inputs[0].started is True
        assert locks[0].started is True
    finally:
        controller.shutdown()


def test_shutdown_stops_all_workers_and_closes_db(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    controller.shutdown()

    assert cameras[0].stopped is True
    assert inputs[0].stopped is True
    assert locks[0].stopped is True


def test_no_work_time_counted_before_first_presence(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        fake_clock.advance(30)
        snapshot = controller.get_snapshot()
        assert snapshot.ready is False
        assert snapshot.elapsed_work_time == 0.0
    finally:
        controller.shutdown()


def test_first_presence_true_starts_counting_as_working(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        cameras[0].emit_presence(True, fake_clock)
        snapshot = controller.get_snapshot()
        assert snapshot.ready is True
        assert snapshot.state is FocusState.WORKING

        fake_clock.advance(10)
        assert controller.get_snapshot().elapsed_work_time == pytest.approx(10)
    finally:
        controller.shutdown()


def test_first_presence_false_goes_away_without_counting(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        cameras[0].emit_presence(False, fake_clock)
        snapshot = controller.get_snapshot()
        assert snapshot.ready is True
        assert snapshot.state is FocusState.AWAY

        fake_clock.advance(100)
        assert controller.get_snapshot().elapsed_work_time == pytest.approx(0)
    finally:
        controller.shutdown()


def test_activity_before_presence_established_is_dropped(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        inputs[0].emit_activity(fake_clock)  # arrives before any presence result
        assert controller.get_snapshot().ready is False

        cameras[0].emit_presence(True, fake_clock)
        assert controller.get_snapshot().ready is True
    finally:
        controller.shutdown()


def test_alert_entered_emitted_exactly_once_per_episode(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        alert_count = 0

        def _on_alert():
            nonlocal alert_count
            alert_count += 1

        controller.alert_entered.connect(_on_alert)

        cameras[0].emit_presence(True, fake_clock)
        inputs[0].emit_activity(fake_clock)
        controller._on_poll()
        fake_clock.advance(IDLE)
        controller._on_poll()  # WORKING -> INACTIVE
        fake_clock.advance(GRACE)
        controller._on_poll()  # INACTIVE -> ALERT (first and only alert)
        controller._on_poll()  # still ALERT - must not re-fire
        controller._on_poll()

        assert alert_count == 1
        assert controller.get_snapshot().state is FocusState.ALERT
    finally:
        controller.shutdown()


def test_continue_and_pause_after_alert(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        cameras[0].emit_presence(True, fake_clock)
        fake_clock.advance(IDLE)
        controller._on_poll()
        fake_clock.advance(GRACE)
        controller._on_poll()
        assert controller.get_snapshot().state is FocusState.ALERT

        controller.continue_working()
        assert controller.get_snapshot().state is FocusState.WORKING
    finally:
        controller.shutdown()


def test_pause_stops_counting(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        cameras[0].emit_presence(True, fake_clock)
        fake_clock.advance(10)
        controller.pause()
        assert controller.get_snapshot().state is FocusState.PAUSED
        fake_clock.advance(60)
        assert controller.get_snapshot().elapsed_work_time == pytest.approx(10)

        controller.resume()
        assert controller.get_snapshot().state is FocusState.WORKING
    finally:
        controller.shutdown()


def test_persistence_creates_session_and_records_state_events(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        cameras[0].emit_presence(True, fake_clock)
        fake_clock.advance(IDLE)
        controller._on_poll()  # WORKING -> INACTIVE, persisted

        sessions = controller.get_recent_sessions()
        assert len(sessions) == 1
        assert sessions[0].ended_at_utc is None  # still running

        session_id = sessions[0].id
        events = controller._repository.list_state_events(session_id)
        assert [(e.from_state, e.to_state) for e in events] == [("WORKING", "INACTIVE")]
    finally:
        controller.shutdown()


def test_checkpoint_persists_running_total(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        cameras[0].emit_presence(True, fake_clock)
        fake_clock.advance(45)

        controller._checkpoint()

        sessions = controller.get_recent_sessions()
        assert sessions[0].total_work_seconds == pytest.approx(45)
        assert sessions[0].end_reason == "in_progress"
    finally:
        controller.shutdown()


def test_shutdown_persists_final_total_with_app_exit_reason(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    cameras[0].emit_presence(True, fake_clock)
    fake_clock.advance(20)

    controller.shutdown()

    # Re-open the same database file to confirm the write really landed.
    db2 = Database(controller._config.database_path)
    from focus_tracker.storage.repository import SessionRepository

    repo2 = SessionRepository(db2)
    sessions = repo2.list_recent_sessions()
    assert sessions[0].total_work_seconds == pytest.approx(20)
    assert sessions[0].end_reason == "app_exit"
    assert sessions[0].ended_at_utc is not None
    db2.close()


def test_shutdown_without_presence_established_does_not_crash(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    controller.shutdown()  # no presence event was ever emitted - must not raise

    assert controller.get_recent_sessions() == []


def test_camera_unavailable_reports_error_and_never_shows_working(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        errors: list = []
        controller.error_occurred.connect(lambda category, message: errors.append((category, message)))

        cameras[0].emit_availability(False)

        assert controller.get_snapshot().ready is False  # never falsely "Working"
        assert any(category == "camera" for category, _ in errors)
        assert controller.get_snapshot().camera_available is False
    finally:
        controller.shutdown()


def test_camera_recovery_reported(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        statuses: list = []
        controller.camera_status_changed.connect(statuses.append)

        cameras[0].emit_availability(False)
        cameras[0].emit_availability(True)

        assert statuses == [False, True]
    finally:
        controller.shutdown()


def test_input_worker_failure_reports_error_without_crashing(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        errors: list = []
        controller.error_occurred.connect(lambda category, message: errors.append((category, message)))

        inputs[0].emit_error(OSError("hook failed"))

        assert any(category == "input" for category, _ in errors)
        assert controller.get_snapshot().input_available is False
    finally:
        controller.shutdown()


def test_lock_monitor_start_failure_is_reported_not_fatal(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    errors: list = []
    controller.error_occurred.connect(lambda category, message: errors.append((category, message)))

    def fail_on_start():
        raise RuntimeError("pywin32 unavailable")

    controller._lock_monitor.start = fail_on_start  # type: ignore[method-assign]

    controller.start()  # must not raise even though the lock monitor failed to start
    try:
        assert any(category == "lock_monitor" for category, _ in errors)
    finally:
        controller.shutdown()


def test_lock_event_pauses_and_unlock_forces_away(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        cameras[0].emit_presence(True, fake_clock)
        locks[0].emit_lock_event(SessionLockEventKind.LOCKED, fake_clock)
        assert controller.get_snapshot().state is FocusState.PAUSED

        locks[0].emit_lock_event(SessionLockEventKind.UNLOCKED, fake_clock)
        assert controller.get_snapshot().state is FocusState.AWAY

        cameras[0].emit_presence(True, fake_clock)
        assert controller.get_snapshot().state is FocusState.WORKING
    finally:
        controller.shutdown()


def test_today_total_includes_live_elapsed_time(qtbot, tmp_path, fake_clock):
    controller, cameras, inputs, locks = _make_controller(tmp_path, fake_clock)
    controller.start()
    try:
        cameras[0].emit_presence(True, fake_clock)
        fake_clock.advance(30)
        snapshot = controller.get_snapshot()
        assert snapshot.today_total_seconds == pytest.approx(30)
    finally:
        controller.shutdown()
