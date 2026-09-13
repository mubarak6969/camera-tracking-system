"""The application controller: owns every background worker and the real
FocusSession, and is the single seam where Qt-awareness begins.

Nothing below core/ or the sensing packages knows Qt exists. This module
is deliberately the first (and only) place that does, so UI widgets never
need to touch FocusSession, SensorBridge, OpenCV, pynput, or SQLite
directly - they only see ControllerSnapshot and three signals.

Startup-state correctness: the existing core still starts a FocusSession
in WORKING for backward compatibility (and to keep its own test suite
intact - see core/state_machine.py). This controller does not fight that;
instead it simply never calls FocusSession.start() (which is what
actually opens the timer's counting segment) until the *first* real
PresenceEvent arrives from the camera. Activity, poll, and lock events
that arrive before that first PresenceEvent are deliberately dropped -
only a camera reading is allowed to end the "starting up" phase, per the
requirement that startup must wait specifically for presence. Once
presence is established, ordinary activity/poll/lock handling proceeds
exactly as SensorBridge already implements it.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from focus_tracker.camera.presence_worker import CameraPresenceWorker
from focus_tracker.concurrency import PeriodicWorker
from focus_tracker.config.settings import AppConfig
from focus_tracker.core.lock_events import SessionLockEvent
from focus_tracker.core.sensor_bridge import SensorBridge
from focus_tracker.core.sensor_events import ActivityEvent, PresenceEvent
from focus_tracker.core.session import FocusSession, PersistableTransition
from focus_tracker.core.state_machine import Clock
from focus_tracker.core.states import FocusState, InvalidTransitionError
from focus_tracker.input_monitor.activity_worker import InputActivityWorker
from focus_tracker.platform_win.session_monitor import WindowsSessionMonitor
from focus_tracker.storage.db import Database, StorageError
from focus_tracker.storage.repository import SessionRecord, SessionRepository
from focus_tracker.timeutil import local_midnight_utc

logger = logging.getLogger(__name__)

_CHECKPOINT_INTERVAL_SECONDS = 30.0


@dataclass(frozen=True)
class ControllerSnapshot:
    """Everything the UI needs to redraw itself, read in one lock-guarded
    call so the UI never sees a half-updated combination of fields."""

    ready: bool
    state: Optional[FocusState]
    elapsed_work_time: float
    today_total_seconds: float
    session_start_utc: Optional[datetime]
    camera_available: Optional[bool]
    input_available: bool


class FocusTrackerController(QObject):
    # Fired exactly once per ALERT episode - never on a repeated poll of an
    # already-ALERT state, because StateMachine only calls its transition
    # callback on an actual state change.
    alert_entered = Signal()
    # (category, message) - "camera", "input", "lock_monitor", or "database".
    error_occurred = Signal(str, str)
    # True once available, False the moment it stops being available.
    camera_status_changed = Signal(bool)

    def __init__(
        self,
        config: AppConfig,
        *,
        clock: Clock = time.monotonic,
        database_factory: Optional[Callable[[], Database]] = None,
        camera_factory: Optional[Callable[..., CameraPresenceWorker]] = None,
        input_factory: Optional[Callable[..., InputActivityWorker]] = None,
        lock_monitor_factory: Optional[Callable[..., object]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._clock = clock
        self._lock = threading.RLock()

        self._db = (database_factory or (lambda: Database(config.database_path)))()
        self._repository = SessionRepository(self._db)

        self._presence_established = False
        self._session_id: Optional[int] = None
        self._session_start_utc: Optional[datetime] = None
        self._cached_today_historical_total = 0.0
        self._camera_available: Optional[bool] = None
        self._input_available = True
        self._shutting_down = False

        self._recover_stale_sessions()

        self._session = FocusSession(
            grace_period_seconds=config.inactivity_grace_period_seconds,
            clock=clock,
            on_state_change=self._on_state_change,
        )
        self._bridge = SensorBridge(
            self._session, idle_threshold_seconds=config.activity_idle_threshold_seconds, clock=clock
        )

        make_camera = camera_factory or CameraPresenceWorker
        self._camera = make_camera(
            on_presence_change=self._on_presence_event,
            sampling_interval_seconds=config.camera_sampling_interval_seconds,
            confirm_frames=config.presence_debounce_frames,
            camera_index=config.camera_index,
            max_retry_backoff_seconds=config.camera_max_retry_backoff_seconds,
            clock=clock,
            on_availability_change=self._on_camera_availability_change,
        )

        make_input = input_factory or InputActivityWorker
        self._input = make_input(
            on_activity=self._on_activity_event,
            collapse_interval_seconds=config.input_event_collapse_interval_seconds,
            clock=clock,
            on_error=self._on_input_error,
        )

        make_lock_monitor = lock_monitor_factory or WindowsSessionMonitor
        self._lock_monitor = make_lock_monitor(on_event=self._on_lock_event, clock=clock)

        self._poller = PeriodicWorker(config.sensor_poll_interval_seconds, self._on_poll, name="SensorPoll")
        self._checkpoint_timer = PeriodicWorker(
            _CHECKPOINT_INTERVAL_SECONDS, self._checkpoint, name="Checkpoint"
        )

        self._refresh_today_historical_total()

    # -- Lifecycle -----------------------------------------------------

    def start(self) -> None:
        self._camera.start()
        self._input.start()
        try:
            self._lock_monitor.start()
        except Exception as exc:
            self._report_error("lock_monitor", f"Lock/sleep detection unavailable: {exc}")
        self._poller.start()
        self._checkpoint_timer.start()

    def shutdown(self) -> None:
        """Stops every background worker and, if a session was actually
        started, writes its final total before closing the database. Safe
        to call even if start() was never called or presence was never
        established.

        Setting _shutting_down first (before touching any worker) means
        every callback below becomes a no-op immediately, even if a
        worker's stop() takes a moment to actually join its thread - no
        in-flight camera/input/lock/poll callback can act on a
        session/repository that shutdown is in the middle of tearing down."""
        with self._lock:
            self._shutting_down = True

        self._poller.stop()
        self._checkpoint_timer.stop()
        try:
            self._lock_monitor.stop()
        except Exception:
            logger.exception("error stopping the session lock monitor")
        self._input.stop()
        self._camera.stop()

        with self._lock:
            if self._presence_established and self._session_id is not None:
                total = self._session.end()
                session_id = self._session_id
            else:
                total = None
                session_id = None

        if session_id is not None and total is not None:
            try:
                self._repository.end_session(session_id, total_work_seconds=total, end_reason="app_exit")
            except StorageError as exc:
                self._report_error("database", str(exc))

        try:
            self._db.close()
        except Exception:
            logger.exception("error closing the database")

    # -- Read-only state for the UI -------------------------------------

    def get_snapshot(self) -> ControllerSnapshot:
        with self._lock:
            if not self._presence_established:
                return ControllerSnapshot(
                    ready=False,
                    state=None,
                    elapsed_work_time=0.0,
                    today_total_seconds=self._cached_today_historical_total,
                    session_start_utc=None,
                    camera_available=self._camera_available,
                    input_available=self._input_available,
                )
            live_elapsed = self._session.elapsed_work_time
            return ControllerSnapshot(
                ready=True,
                state=self._session.state,
                elapsed_work_time=live_elapsed,
                today_total_seconds=self._cached_today_historical_total + live_elapsed,
                session_start_utc=self._session_start_utc,
                camera_available=self._camera_available,
                input_available=self._input_available,
            )

    def get_recent_sessions(self, limit: int = 20) -> list[SessionRecord]:
        try:
            return self._repository.list_recent_sessions(limit=limit)
        except StorageError as exc:
            self._report_error("database", str(exc))
            return []

    # -- User actions (safe to call from the UI thread) ------------------

    def pause(self) -> None:
        with self._lock:
            if self._shutting_down or not self._presence_established:
                return
            try:
                self._session.pause()
            except InvalidTransitionError:
                pass  # UI got out of sync with the real state - ignore rather than crash

    def resume(self) -> None:
        with self._lock:
            if self._shutting_down or not self._presence_established:
                return
            try:
                self._session.resume()
            except InvalidTransitionError:
                pass

    def continue_working(self) -> None:
        with self._lock:
            if self._shutting_down or not self._presence_established:
                return
            try:
                self._session.continue_working()
            except InvalidTransitionError:
                pass

    # -- Sensor callbacks (may run on the camera/input/poll/lock threads) -

    def _on_presence_event(self, event: PresenceEvent) -> None:
        with self._lock:
            if self._shutting_down:
                return
            first_time = not self._presence_established
            if first_time:
                self._presence_established = True
                self._session_start_utc = datetime.now(timezone.utc)
                self._session.start()
                self._session_id = self._create_session_row()
            self._bridge.handle_presence(event)
        if first_time:
            self._refresh_today_historical_total()

    def _on_activity_event(self, event: ActivityEvent) -> None:
        with self._lock:
            if self._shutting_down or not self._presence_established:
                return
            self._bridge.handle_activity(event)

    def _on_poll(self) -> None:
        with self._lock:
            if self._shutting_down or not self._presence_established:
                return
            self._bridge.poll()

    def _on_lock_event(self, event: SessionLockEvent) -> None:
        with self._lock:
            if self._shutting_down or not self._presence_established:
                return
            self._bridge.handle_lock_event(event)

    def _on_camera_availability_change(self, available: bool) -> None:
        if self._shutting_down:
            return
        self._camera_available = available
        self.camera_status_changed.emit(available)
        if not available:
            self._report_error("camera", "Camera unavailable - retrying in the background.")

    def _on_input_error(self, exc: Exception) -> None:
        if self._shutting_down:
            return
        self._input_available = False
        self._report_error("input", f"Keyboard/mouse monitoring failed to start: {exc}")

    def _on_state_change(self, transition: PersistableTransition) -> None:
        # Called synchronously from inside FocusSession, itself called
        # synchronously from one of the locked methods above - self._lock
        # is already held by the caller on this same thread, so this must
        # never try to acquire it again.
        if self._session_id is not None:
            try:
                self._repository.record_state_event(
                    self._session_id,
                    transition.from_state.value,
                    transition.to_state.value,
                    transition.occurred_at_utc,
                )
            except StorageError as exc:
                self._report_error("database", str(exc))
        if transition.to_state is FocusState.ALERT:
            self.alert_entered.emit()

    # -- Persistence helpers ---------------------------------------------

    def _create_session_row(self) -> Optional[int]:
        try:
            return self._repository.create_session()
        except StorageError as exc:
            self._report_error("database", str(exc))
            return None

    def _recover_stale_sessions(self) -> None:
        """Runs once, at startup, before any new session is created. Any
        row still marked NULL/"in_progress" was left behind by a crash or a
        forced kill of a previous run (a clean exit always writes
        end_reason="app_exit"). Finalizes each one with whatever total was
        last checkpointed - never discarding it - and a distinct
        "interrupted" reason, so history stays honest and no ghost
        "in_progress" row lingers forever. This never creates a new
        session and never touches the session this run will create later,
        so it cannot produce duplicates."""
        try:
            stale_sessions = self._repository.list_unfinalized_sessions()
        except StorageError as exc:
            self._report_error("database", str(exc))
            return
        now = datetime.now(timezone.utc)
        for stale in stale_sessions:
            try:
                self._repository.end_session(
                    stale.id,
                    total_work_seconds=stale.total_work_seconds,
                    end_reason="interrupted",
                    ended_at=now,
                )
            except StorageError as exc:
                self._report_error("database", str(exc))

    def _checkpoint(self) -> None:
        """Runs every _CHECKPOINT_INTERVAL_SECONDS so a crash or unexpected
        shutdown loses at most one interval's worth of the running total,
        never the whole session."""
        with self._lock:
            if self._shutting_down or not self._presence_established or self._session_id is None:
                return
            session_id = self._session_id
            total = self._session.elapsed_work_time
        try:
            self._repository.end_session(session_id, total_work_seconds=total, end_reason="in_progress")
        except StorageError as exc:
            self._report_error("database", str(exc))
        self._refresh_today_historical_total()

    def _refresh_today_historical_total(self) -> None:
        with self._lock:
            if self._shutting_down:
                return
            session_id = self._session_id
        today_start_utc = local_midnight_utc()
        try:
            total = self._repository.get_total_work_seconds_since(
                today_start_utc, exclude_session_id=session_id
            )
        except StorageError as exc:
            self._report_error("database", str(exc))
            return
        with self._lock:
            self._cached_today_historical_total = total

    def _report_error(self, category: str, message: str) -> None:
        logger.error("%s: %s", category, message)
        self.error_occurred.emit(category, message)
