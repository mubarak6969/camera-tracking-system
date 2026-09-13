"""The "are you still working?" inactivity alert.

Deliberately non-modal (.show(), not .exec()) so it can never block the
Qt event loop that keeps the sensor-thread signal queue draining.
Dismissing it any way other than clicking Continue - the window's X
button, Alt+F4, Esc - is treated exactly like clicking Pause: this alert
must have deterministic behavior, and silently resuming work just because
the dialog was closed is exactly the failure mode to avoid.
"""
from __future__ import annotations

import winsound

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class InactivityAlertDialog(QDialog):
    continue_clicked = Signal()
    pause_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Still there?")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setModal(False)
        self._resolved = False

        message = QLabel("Are you still working?")
        message.setStyleSheet("font-size: 15px; padding: 4px;")

        continue_button = QPushButton("Continue")
        continue_button.setDefault(True)
        continue_button.clicked.connect(self._on_continue)

        pause_button = QPushButton("Pause")
        pause_button.clicked.connect(self._on_pause)

        buttons_row = QHBoxLayout()
        buttons_row.addWidget(continue_button)
        buttons_row.addWidget(pause_button)

        layout = QVBoxLayout()
        layout.addWidget(message)
        layout.addLayout(buttons_row)
        self.setLayout(layout)

        self._play_alert_sound()

    def _play_alert_sound(self) -> None:
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass  # a sound-device problem must never block the alert itself

    def _on_continue(self) -> None:
        self._resolved = True
        self.continue_clicked.emit()

    def _on_pause(self) -> None:
        self._resolved = True
        self.pause_clicked.emit()

    def mark_resolved(self) -> None:
        """Lets the owner (MainWindow) close this dialog after already
        having acted on Continue/Pause without closeEvent() re-triggering
        Pause as if the dialog had been dismissed unresolved."""
        self._resolved = True

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._resolved:
            self._resolved = True
            self.pause_clicked.emit()
        event.accept()
