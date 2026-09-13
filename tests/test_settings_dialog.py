from __future__ import annotations

from focus_tracker.config.settings import AppConfig
from focus_tracker.config.store import load_config
from focus_tracker.ui.settings_dialog import SettingsDialog


def test_saving_valid_values_persists_them(qtbot, tmp_path, monkeypatch):
    config = AppConfig(database_path=tmp_path / "db.sqlite")
    dialog = SettingsDialog(config)
    qtbot.addWidget(dialog)

    monkeypatch.setattr(
        "focus_tracker.ui.settings_dialog.QMessageBox.information", lambda *a, **k: None
    )

    dialog._grace_period.setValue(90)
    dialog._camera_index.setValue(2)
    dialog._on_save()

    reloaded = load_config(config)
    assert reloaded.inactivity_grace_period_seconds == 90
    assert reloaded.camera_index == 2


def test_saving_invalid_values_shows_warning_and_does_not_persist(qtbot, tmp_path, monkeypatch):
    config = AppConfig(database_path=tmp_path / "db.sqlite")
    dialog = SettingsDialog(config)
    qtbot.addWidget(dialog)

    warnings: list = []
    monkeypatch.setattr(
        "focus_tracker.ui.settings_dialog.QMessageBox.warning",
        lambda *a, **k: warnings.append(a),
    )

    # The spin box itself clamps to its minimum (5s), so force an invalid
    # candidate config directly to exercise validate_config's own rejection
    # path, the same one a corrupted settings file would also hit.
    dialog._config = AppConfig(database_path=config.database_path, inactivity_grace_period_seconds=-1)
    dialog._grace_period.setValue(dialog._grace_period.minimum())
    original_build = dialog.build_candidate_config
    dialog.build_candidate_config = lambda: AppConfig(
        database_path=config.database_path, inactivity_grace_period_seconds=-1
    )

    dialog._on_save()

    assert len(warnings) == 1
    reloaded = load_config(config)
    assert reloaded == config  # nothing was persisted
