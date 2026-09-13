"""Webcam presence detection - never face recognition, never persisted frames.

CameraPresenceWorker is the module's public entry point; it depends only
on the small FrameSource/FaceDetector interfaces defined alongside it, so
it can be tested with fakes and never leaks a frame outside this package.
"""
from focus_tracker.camera.presence_worker import CameraPresenceWorker

__all__ = ["CameraPresenceWorker"]
