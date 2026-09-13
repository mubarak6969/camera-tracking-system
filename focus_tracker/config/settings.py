"""Central application configuration.

Every value has a sensible default so the app runs out of the box. There
are no secrets or external service credentials in this project, so there
is deliberately no `.env` file - see the README for that decision.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_database_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    return base / "AIFocusTracker" / "focus_tracker.db"


@dataclass(frozen=True)
class AppConfig:
    # Core state-machine behavior.
    inactivity_grace_period_seconds: float = 120.0

    # Camera presence detection: how often to sample a frame, how many
    # consecutive frames must agree before a presence change is trusted
    # (avoids flicker on a single bad read), which camera to open, and how
    # long to back off between reconnect attempts when it is unavailable.
    camera_sampling_interval_seconds: float = 1.0
    presence_debounce_frames: int = 3
    camera_index: int = 0
    camera_max_retry_backoff_seconds: float = 30.0

    # Input monitoring: how long the system can go without a keyboard/mouse
    # event before it is considered idle, and how often rapid raw pynput
    # callbacks are collapsed into a single ActivityEvent.
    activity_idle_threshold_seconds: float = 5.0
    input_event_collapse_interval_seconds: float = 1.0

    # How often SensorBridge.poll() is driven from a background scheduler
    # to check the idle threshold and the state machine's grace period.
    sensor_poll_interval_seconds: float = 1.0

    database_path: Path = field(default_factory=_default_database_path)
