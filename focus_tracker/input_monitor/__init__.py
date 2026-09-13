"""System-wide keyboard/mouse activity monitoring - timestamps only, never
key names, typed text, or mouse coordinates.
"""
from focus_tracker.input_monitor.activity_worker import InputActivityWorker

__all__ = ["InputActivityWorker"]
