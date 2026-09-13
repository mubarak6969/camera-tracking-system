"""Loads and saves the user-editable subset of AppConfig as a small JSON
file next to the database, so the Settings dialog can persist changes
across restarts without turning AppConfig itself into anything more than
the plain frozen dataclass it already is.

Only the fields a user can actually change through the Settings dialog are
read/written here - database_path and the two collapse/poll intervals stay
at their code defaults, since they are not exposed as user settings in
this phase.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path
from typing import Any, Dict

from focus_tracker.config.settings import AppConfig

logger = logging.getLogger(__name__)

_EDITABLE_FIELDS = (
    "inactivity_grace_period_seconds",
    "camera_sampling_interval_seconds",
    "presence_debounce_frames",
    "camera_index",
    "camera_max_retry_backoff_seconds",
    "activity_idle_threshold_seconds",
)


def default_settings_path(config: AppConfig) -> Path:
    return config.database_path.parent / "settings.json"


def load_config(base: AppConfig, path: Path | None = None) -> AppConfig:
    """Returns a new AppConfig with any saved editable fields overlaid onto
    `base`. Falls back silently to `base` unchanged if the file is missing,
    unreadable, or contains invalid values - a corrupt settings file must
    never prevent the app from starting."""
    settings_path = path or default_settings_path(base)
    if not settings_path.exists():
        return base

    try:
        raw: Dict[str, Any] = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("failed to read settings file %s - using defaults", settings_path)
        return base

    overrides = {key: raw[key] for key in _EDITABLE_FIELDS if key in raw}
    try:
        candidate = dataclasses.replace(base, **overrides)
        validate_config(candidate)
    except (TypeError, ValueError):
        logger.warning("settings file %s contained invalid values - using defaults", settings_path)
        return base
    return candidate


def save_config(config: AppConfig, path: Path | None = None) -> None:
    settings_path = path or default_settings_path(config)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    data = {key: getattr(config, key) for key in _EDITABLE_FIELDS}
    settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def validate_config(config: AppConfig) -> None:
    """Raises ValueError with a human-readable message on the first invalid
    field found. Called both when loading a saved file and when the
    Settings dialog is about to save one."""
    if config.inactivity_grace_period_seconds <= 0:
        raise ValueError("Inactivity grace period must be greater than 0 seconds.")
    if config.camera_sampling_interval_seconds <= 0:
        raise ValueError("Camera sampling interval must be greater than 0 seconds.")
    if config.presence_debounce_frames < 1:
        raise ValueError("Presence debounce frames must be at least 1.")
    if config.camera_index < 0:
        raise ValueError("Camera index cannot be negative.")
    if config.camera_max_retry_backoff_seconds <= 0:
        raise ValueError("Camera max retry backoff must be greater than 0 seconds.")
    if config.activity_idle_threshold_seconds <= 0:
        raise ValueError("Activity idle threshold must be greater than 0 seconds.")
