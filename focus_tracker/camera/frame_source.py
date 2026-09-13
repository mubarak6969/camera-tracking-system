"""Thin wrapper around cv2.VideoCapture.

Isolated into its own tiny class (rather than calling cv2.VideoCapture
directly from the worker) purely so tests can substitute a fake frame
source and exercise retry/backoff/failure handling without a real
webcam. Nothing here processes or stores frames - it just hands the raw
BGR array to whoever calls read(), one call at a time.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, Tuple


class FrameSource(Protocol):
    def is_opened(self) -> bool: ...

    def read(self) -> Tuple[bool, Optional[Any]]: ...

    def release(self) -> None: ...


class OpenCvFrameSource:
    """Opens the given camera index via OpenCV's DirectShow backend, which
    is the reliable choice on Windows."""

    def __init__(self, camera_index: int = 0) -> None:
        import cv2  # imported lazily so this module only needs cv2 when actually used

        self._capture = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)

    def is_opened(self) -> bool:
        return bool(self._capture.isOpened())

    def read(self) -> Tuple[bool, Optional[Any]]:
        return self._capture.read()

    def release(self) -> None:
        self._capture.release()
