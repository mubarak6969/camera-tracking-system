"""Background webcam-presence worker.

Samples the camera at a low, configurable rate on its own thread (via
concurrency.PeriodicWorker), runs a face detector on each frame, debounces
the result, and emits a PresenceEvent *only when the debounced state
changes*. It never hands a frame to anything outside this module, and it
never stores one - each frame is discarded the moment detect_face() has
looked at it.

Camera failures (never opened, unplugged mid-session, busy with another
app, a bad read) are treated the same way: back off with a bounded,
doubling delay and keep retrying, rather than crashing or forcing a
presence conclusion the camera cannot actually support.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

from focus_tracker.camera.debounce import PresenceDebouncer
from focus_tracker.camera.detector import FaceDetector, HaarCascadeFaceDetector
from focus_tracker.camera.frame_source import FrameSource, OpenCvFrameSource
from focus_tracker.concurrency import PeriodicWorker
from focus_tracker.core.sensor_events import PresenceEvent
from focus_tracker.core.state_machine import Clock

logger = logging.getLogger(__name__)

FrameSourceFactory = Callable[[], FrameSource]


class CameraPresenceWorker:
    def __init__(
        self,
        on_presence_change: Callable[[PresenceEvent], None],
        sampling_interval_seconds: float = 1.0,
        confirm_frames: int = 3,
        camera_index: int = 0,
        max_retry_backoff_seconds: float = 30.0,
        clock: Clock = time.monotonic,
        frame_source_factory: Optional[FrameSourceFactory] = None,
        detector: Optional[FaceDetector] = None,
        on_availability_change: Optional[Callable[[bool], None]] = None,
    ) -> None:
        self._on_presence_change = on_presence_change
        self._on_availability_change = on_availability_change
        self._camera_available: Optional[bool] = None
        self._clock = clock
        self._frame_source_factory: FrameSourceFactory = (
            frame_source_factory
            if frame_source_factory is not None
            else (lambda: OpenCvFrameSource(camera_index))
        )
        self._detector = detector if detector is not None else HaarCascadeFaceDetector()
        self._debouncer = PresenceDebouncer(confirm_frames=confirm_frames)
        self._max_retry_backoff_seconds = max_retry_backoff_seconds

        self._frame_source: Optional[FrameSource] = None
        self._last_emitted: Optional[bool] = None
        self._retry_backoff_seconds = 1.0
        self._next_retry_at = 0.0
        self._lock = threading.Lock()

        self._worker = PeriodicWorker(
            interval_seconds=sampling_interval_seconds,
            action=self._sample_once,
            name="CameraPresenceWorker",
        )

    def start(self) -> None:
        self._worker.start()

    def stop(self) -> None:
        self._worker.stop()
        self._release_frame_source()

    @property
    def is_running(self) -> bool:
        return self._worker.is_running

    def _sample_once(self) -> None:
        with self._lock:
            source = self._ensure_frame_source()
            if source is None:
                return
            try:
                ok, frame = source.read()
            except Exception:
                logger.exception("CameraPresenceWorker: frame read raised, releasing camera")
                self._release_frame_source()
                self._mark_unavailable()
                return

            if not ok or frame is None:
                logger.warning("CameraPresenceWorker: frame read failed, releasing camera")
                self._release_frame_source()
                self._mark_unavailable()
                return

            try:
                raw_present = self._detector.detect_face(frame)
            except Exception:
                logger.exception("CameraPresenceWorker: detector raised, skipping this frame")
                return
            finally:
                del frame  # drop the reference as soon as detection is done; never retained

            debounced = self._debouncer.observe(raw_present)
            if debounced != self._last_emitted:
                self._last_emitted = debounced
                self._on_presence_change(
                    PresenceEvent(present=debounced, monotonic_timestamp=self._clock())
                )

    def _ensure_frame_source(self) -> Optional[FrameSource]:
        if self._frame_source is not None and self._frame_source.is_opened():
            return self._frame_source

        now = self._clock()
        if now < self._next_retry_at:
            return None  # still backing off from a previous failure

        try:
            source: Optional[FrameSource] = self._frame_source_factory()
        except Exception:
            logger.exception("CameraPresenceWorker: failed to construct a frame source")
            source = None

        if source is None or not source.is_opened():
            self._schedule_retry(now)
            self._mark_unavailable()
            return None

        self._frame_source = source
        self._retry_backoff_seconds = 1.0
        self._mark_available()
        return source

    def _mark_available(self) -> None:
        if self._camera_available is not True:
            self._camera_available = True
            if self._on_availability_change is not None:
                self._on_availability_change(True)

    def _mark_unavailable(self) -> None:
        if self._camera_available is not False:
            self._camera_available = False
            if self._on_availability_change is not None:
                self._on_availability_change(False)

    def _schedule_retry(self, now: float) -> None:
        self._next_retry_at = now + self._retry_backoff_seconds
        self._retry_backoff_seconds = min(
            self._retry_backoff_seconds * 2, self._max_retry_backoff_seconds
        )

    def _release_frame_source(self) -> None:
        if self._frame_source is not None:
            try:
                self._frame_source.release()
            except Exception:
                logger.exception("CameraPresenceWorker: error releasing camera")
            self._frame_source = None
