"""Exercises CameraPresenceWorker's sampling/debounce/retry/shutdown logic
with a fake frame source and a fake detector - no real webcam involved.

`_sample_once()` (normally driven by a PeriodicWorker on its own thread)
is called directly so each test controls exactly when a "frame" is
sampled, using the fake clock to control backoff timing deterministically.
"""
from __future__ import annotations

from typing import List

from focus_tracker.camera.presence_worker import CameraPresenceWorker
from focus_tracker.core.sensor_events import PresenceEvent


class FakeFrameSource:
    def __init__(self, opened: bool = True) -> None:
        self._opened = opened
        self.released = False
        self.read_queue: list = []

    def is_opened(self) -> bool:
        return self._opened and not self.released

    def read(self):
        if not self.read_queue:
            return True, "frame"
        item = self.read_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def release(self) -> None:
        self.released = True
        self._opened = False


class FakeDetector:
    def __init__(self, results: list) -> None:
        self._results = list(results)

    def detect_face(self, frame) -> bool:
        if not self._results:
            return True
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _make_worker(fake_clock, factory, detector, confirm_frames=1) -> CameraPresenceWorker:
    emitted: List[PresenceEvent] = []
    worker = CameraPresenceWorker(
        on_presence_change=emitted.append,
        confirm_frames=confirm_frames,
        clock=fake_clock,
        frame_source_factory=factory,
        detector=detector,
    )
    worker.emitted = emitted  # type: ignore[attr-defined]
    return worker


def test_emits_presence_event_only_on_debounced_change(fake_clock):
    source = FakeFrameSource(opened=True)
    detector = FakeDetector([True, True, False])
    worker = _make_worker(fake_clock, lambda: source, detector, confirm_frames=1)

    worker._sample_once()  # True: first sample always emits (nothing emitted yet)
    worker._sample_once()  # True again: no change, no emit
    worker._sample_once()  # False: changes, emits

    assert [e.present for e in worker.emitted] == [True, False]


def test_debounce_absorbs_a_single_bad_frame(fake_clock):
    source = FakeFrameSource(opened=True)
    detector = FakeDetector([True, True, False, True, True])
    worker = _make_worker(fake_clock, lambda: source, detector, confirm_frames=3)

    for _ in range(5):
        worker._sample_once()

    # Only the initial True was ever emitted - the lone False observation
    # never reached the confirm_frames=3 threshold needed to flip state.
    assert [e.present for e in worker.emitted] == [True]


def test_confirmed_negative_run_does_flip_to_away(fake_clock):
    source = FakeFrameSource(opened=True)
    detector = FakeDetector([True, False, False, False])
    worker = _make_worker(fake_clock, lambda: source, detector, confirm_frames=3)

    for _ in range(4):
        worker._sample_once()

    assert [e.present for e in worker.emitted] == [True, False]


def test_camera_failure_retries_with_bounded_backoff(fake_clock):
    open_attempts: list = []

    def factory():
        source = FakeFrameSource(opened=len(open_attempts) >= 2)
        open_attempts.append(source)
        return source

    detector = FakeDetector([True])
    worker = _make_worker(fake_clock, factory, detector, confirm_frames=1)

    worker._sample_once()  # attempt 1: fails to open
    assert len(open_attempts) == 1
    assert worker.emitted == []

    fake_clock.advance(0.5)
    worker._sample_once()  # still inside the 1s backoff window
    assert len(open_attempts) == 1

    fake_clock.advance(0.6)  # now past the 1s backoff
    worker._sample_once()  # attempt 2: fails again, backoff doubles to 2s
    assert len(open_attempts) == 2

    fake_clock.advance(1.5)
    worker._sample_once()  # still inside the 2s backoff window
    assert len(open_attempts) == 2

    fake_clock.advance(1.0)  # now past the 2s backoff
    worker._sample_once()  # attempt 3: succeeds
    assert len(open_attempts) == 3
    assert worker.emitted and worker.emitted[-1].present is True


def test_read_failure_releases_and_reopens_next_sample(fake_clock):
    first_source = FakeFrameSource(opened=True)
    first_source.read_queue = [RuntimeError("device error")]
    second_source = FakeFrameSource(opened=True)
    sources = [first_source, second_source]

    def factory():
        return sources.pop(0)

    detector = FakeDetector([True])
    worker = _make_worker(fake_clock, factory, detector, confirm_frames=1)

    worker._sample_once()  # opens first_source, read() raises -> released
    assert first_source.released is True
    assert worker.emitted == []

    worker._sample_once()  # opens second_source, reads fine
    assert worker.emitted and worker.emitted[-1].present is True


def test_detector_exception_skips_frame_without_releasing_camera(fake_clock):
    source = FakeFrameSource(opened=True)
    detector = FakeDetector([RuntimeError("bad frame"), True])
    worker = _make_worker(fake_clock, lambda: source, detector, confirm_frames=1)

    worker._sample_once()  # detector raises - must not crash or release camera
    assert source.released is False
    assert worker.emitted == []

    worker._sample_once()  # same (still-open) camera, detector succeeds this time
    assert worker.emitted and worker.emitted[-1].present is True


def test_stop_releases_the_camera_cleanly(fake_clock):
    source = FakeFrameSource(opened=True)
    detector = FakeDetector([True])
    worker = _make_worker(fake_clock, lambda: source, detector, confirm_frames=1)

    worker._sample_once()
    assert source.released is False

    worker.stop()
    assert source.released is True
    assert worker.is_running is False
