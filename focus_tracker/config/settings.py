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

    # Reserved for the camera module (not implemented yet): how often to
    # sample a frame, and how many consecutive frames must agree before
    # a presence change is trusted, to avoid flicker on a single bad read.
    camera_sampling_interval_seconds: float = 1.0
    presence_debounce_frames: int = 3

    # Reserved for the input-monitoring module (not implemented yet): how
    # long the system can go without a keyboard/mouse event before it is
    # considered idle.
    activity_idle_threshold_seconds: float = 5.0

    database_path: Path = field(default_factory=_default_database_path)
