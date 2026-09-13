"""Event vocabulary for Windows session/power notifications.

Kept separate from sensor_events.py because lock/unlock/sleep/wake come
from an optional, platform-specific source (see focus_tracker/platform_win/)
rather than from the camera or input-monitor sensing loop, and a system
without that component wired up should still work with plain presence and
activity events.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SessionLockEventKind(Enum):
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"
    SLEEP = "SLEEP"
    WAKE = "WAKE"


@dataclass(frozen=True)
class SessionLockEvent:
    kind: SessionLockEventKind
    monotonic_timestamp: float
