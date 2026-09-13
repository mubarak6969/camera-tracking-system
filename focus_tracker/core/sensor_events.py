"""Event vocabulary the sensing layer uses to talk to the core layer.

Defined here, in core, so the dependency points inward: focus_tracker's
camera and input_monitor packages import these types, but core never
imports OpenCV or pynput. This is what keeps core independently testable
without any sensing hardware.

Deliberately minimal - PresenceEvent carries only a boolean and a
timestamp, ActivityEvent only a timestamp. Neither can ever carry a
frame, a key, or a coordinate, because those fields simply do not exist
on these types.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PresenceEvent:
    present: bool
    monotonic_timestamp: float


@dataclass(frozen=True)
class ActivityEvent:
    monotonic_timestamp: float
