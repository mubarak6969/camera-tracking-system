"""Face-presence detection - not face recognition.

Uses OpenCV's bundled Haar cascade classifier: it ships inside the
opencv-python wheel already (no extra model file to download or package),
runs fast enough on a single downscaled frame per sample, and only ever
answers "is at least one face-shaped region present", never who it is.
That combination is what makes it a good fit for a packaged Windows app -
no bundling concerns, no per-identity data of any kind.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol


class FaceDetector(Protocol):
    def detect_face(self, frame: Any) -> bool: ...


class HaarCascadeFaceDetector:
    def __init__(
        self,
        scale_factor: float = 1.2,
        min_neighbors: int = 5,
        min_size: tuple[int, int] = (60, 60),
        cascade: Optional[Any] = None,
    ) -> None:
        """`cascade` can be injected in tests (e.g. a Mock with a
        `detectMultiScale` method) to avoid depending on a real classifier
        or a real face image."""
        self._scale_factor = scale_factor
        self._min_neighbors = min_neighbors
        self._min_size = min_size
        self._cascade = cascade if cascade is not None else self._load_default_cascade()

    def detect_face(self, frame: Any) -> bool:
        import cv2

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(
            gray,
            scaleFactor=self._scale_factor,
            minNeighbors=self._min_neighbors,
            minSize=self._min_size,
        )
        return len(faces) > 0

    @staticmethod
    def _load_default_cascade() -> Any:
        import cv2

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            raise RuntimeError(f"failed to load Haar cascade classifier from {cascade_path}")
        return cascade
