"""Tests the detector's logic against a mocked cascade classifier, never a
real webcam frame or a real face image - matching the requirement that the
automated suite must not depend on hardware."""
from __future__ import annotations

from unittest.mock import Mock

import numpy as np

from focus_tracker.camera.detector import HaarCascadeFaceDetector


def _make_frame() -> np.ndarray:
    # Any array of the right shape works - the mocked cascade never
    # actually inspects pixel values.
    return np.zeros((480, 640, 3), dtype=np.uint8)


def test_no_faces_returns_false():
    mock_cascade = Mock()
    mock_cascade.detectMultiScale.return_value = ()
    detector = HaarCascadeFaceDetector(cascade=mock_cascade)

    assert detector.detect_face(_make_frame()) is False


def test_one_face_returns_true():
    mock_cascade = Mock()
    mock_cascade.detectMultiScale.return_value = [(10, 10, 100, 100)]
    detector = HaarCascadeFaceDetector(cascade=mock_cascade)

    assert detector.detect_face(_make_frame()) is True


def test_multiple_faces_still_returns_true():
    mock_cascade = Mock()
    mock_cascade.detectMultiScale.return_value = [(10, 10, 100, 100), (200, 200, 80, 80)]
    detector = HaarCascadeFaceDetector(cascade=mock_cascade)

    assert detector.detect_face(_make_frame()) is True


def test_detector_never_retains_a_reference_to_the_frame():
    mock_cascade = Mock()
    mock_cascade.detectMultiScale.return_value = ()
    detector = HaarCascadeFaceDetector(cascade=mock_cascade)

    detector.detect_face(_make_frame())

    assert not any(
        isinstance(value, np.ndarray) for value in vars(detector).values()
    )


def test_empty_cascade_raises_at_construction(monkeypatch):
    import cv2
    import pytest

    empty_cascade = Mock()
    empty_cascade.empty.return_value = True
    monkeypatch.setattr(cv2, "CascadeClassifier", lambda _path: empty_cascade)

    with pytest.raises(RuntimeError):
        HaarCascadeFaceDetector()  # no injected cascade -> exercises _load_default_cascade
