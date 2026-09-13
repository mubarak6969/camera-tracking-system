"""Settings form for the user-editable AppConfig fields.

Every change here requires an app restart to take effect - hot-reloading
a running FocusSession's grace period or rebuilding a live camera worker
is real added complexity for a first settings screen, so this phase keeps
it simple and says so plainly rather than pretending to apply changes live.
"""
from __future__ import annotations

import dataclasses

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from focus_tracker.config.settings import AppConfig
from focus_tracker.config.store import save_config, validate_config


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._config = config

        self._grace_period = QDoubleSpinBox()
        self._grace_period.setRange(5.0, 3600.0)
        self._grace_period.setSuffix(" s")
        self._grace_period.setValue(config.inactivity_grace_period_seconds)

        self._sampling_interval = QDoubleSpinBox()
        self._sampling_interval.setRange(0.1, 60.0)
        self._sampling_interval.setSuffix(" s")
        self._sampling_interval.setValue(config.camera_sampling_interval_seconds)

        self._debounce_frames = QSpinBox()
        self._debounce_frames.setRange(1, 30)
        self._debounce_frames.setValue(config.presence_debounce_frames)

        self._camera_index = QSpinBox()
        self._camera_index.setRange(0, 10)
        self._camera_index.setValue(config.camera_index)

        form = QFormLayout()
        form.addRow("Inactivity grace period:", self._grace_period)
        form.addRow("Camera sampling interval:", self._sampling_interval)
        form.addRow("Presence debounce (frames):", self._debounce_frames)
        form.addRow("Camera index:", self._camera_index)

        note = QLabel("Changes take effect after restarting AI Focus Tracker.")
        note.setStyleSheet("color: #666; font-size: 11px;")
        note.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def build_candidate_config(self) -> AppConfig:
        return dataclasses.replace(
            self._config,
            inactivity_grace_period_seconds=self._grace_period.value(),
            camera_sampling_interval_seconds=self._sampling_interval.value(),
            presence_debounce_frames=self._debounce_frames.value(),
            camera_index=self._camera_index.value(),
        )

    def _on_save(self) -> None:
        candidate = self.build_candidate_config()
        try:
            validate_config(candidate)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid settings", str(exc))
            return
        save_config(candidate)
        QMessageBox.information(
            self, "Settings saved", "Restart AI Focus Tracker for changes to take effect."
        )
        self.accept()
