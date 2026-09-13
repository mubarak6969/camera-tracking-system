"""Application-layer wiring between the sensing/core layers and the UI.

FocusTrackerController is the only piece of the app that is both
Qt-aware (it emits signals) and business-logic-aware (it owns the real
FocusSession, SensorBridge, and workers). UI widgets talk only to the
controller - never to OpenCV, pynput, or SQLite directly.
"""
from focus_tracker.app.controller import ControllerSnapshot, FocusTrackerController

__all__ = ["ControllerSnapshot", "FocusTrackerController"]
