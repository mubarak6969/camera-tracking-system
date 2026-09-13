from __future__ import annotations

import pytest

from focus_tracker.config.settings import AppConfig
from focus_tracker.config.store import load_config, save_config, validate_config


def test_load_config_returns_base_when_no_file_exists(tmp_path):
    base = AppConfig(database_path=tmp_path / "db.sqlite")
    loaded = load_config(base, path=tmp_path / "settings.json")
    assert loaded == base


def test_save_then_load_round_trips_editable_fields(tmp_path):
    base = AppConfig(database_path=tmp_path / "db.sqlite")
    settings_path = tmp_path / "settings.json"
    changed = AppConfig(
        database_path=base.database_path,
        inactivity_grace_period_seconds=60.0,
        camera_sampling_interval_seconds=2.0,
        presence_debounce_frames=5,
        camera_index=1,
    )

    save_config(changed, path=settings_path)
    loaded = load_config(base, path=settings_path)

    assert loaded.inactivity_grace_period_seconds == 60.0
    assert loaded.camera_sampling_interval_seconds == 2.0
    assert loaded.presence_debounce_frames == 5
    assert loaded.camera_index == 1


def test_load_config_falls_back_to_base_on_corrupt_file(tmp_path):
    base = AppConfig(database_path=tmp_path / "db.sqlite")
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{not valid json", encoding="utf-8")

    loaded = load_config(base, path=settings_path)

    assert loaded == base


def test_load_config_falls_back_to_base_on_invalid_values(tmp_path):
    base = AppConfig(database_path=tmp_path / "db.sqlite")
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"inactivity_grace_period_seconds": -5}', encoding="utf-8")

    loaded = load_config(base, path=settings_path)

    assert loaded == base


@pytest.mark.parametrize(
    "overrides",
    [
        {"inactivity_grace_period_seconds": 0},
        {"inactivity_grace_period_seconds": -1},
        {"camera_sampling_interval_seconds": 0},
        {"presence_debounce_frames": 0},
        {"camera_index": -1},
        {"camera_max_retry_backoff_seconds": 0},
        {"activity_idle_threshold_seconds": 0},
    ],
)
def test_validate_config_rejects_invalid_values(overrides):
    import dataclasses

    config = dataclasses.replace(AppConfig(), **overrides)
    with pytest.raises(ValueError):
        validate_config(config)


def test_validate_config_accepts_defaults():
    validate_config(AppConfig())  # must not raise
