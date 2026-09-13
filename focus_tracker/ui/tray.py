"""Windows system tray icon: minimize-to-tray, restore, pause/resume,
status, and a clean exit.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from focus_tracker.app.controller import FocusTrackerController
from focus_tracker.core.states import FocusState

_STATE_COLORS = {
    None: QColor("#9e9e9e"),
    FocusState.WORKING: QColor("#2e7d32"),
    FocusState.INACTIVE: QColor("#f9a825"),
    FocusState.ALERT: QColor("#e65100"),
    FocusState.PAUSED: QColor("#616161"),
    FocusState.AWAY: QColor("#c62828"),
}


def _make_status_icon(color: QColor) -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 24, 24)
    painter.end()
    return QIcon(pixmap)


class TrayController(QObject):
    def __init__(self, main_window, controller: FocusTrackerController, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._main_window = main_window
        self._controller = controller

        self.tray_icon = QSystemTrayIcon(_make_status_icon(_STATE_COLORS[None]), main_window)
        self.tray_icon.setToolTip("AI Focus Tracker - starting…")

        menu = QMenu()
        self._status_action = menu.addAction("Status: Starting…")
        self._status_action.setEnabled(False)
        menu.addSeparator()
        show_action = menu.addAction("Show")
        show_action.triggered.connect(self._on_show)
        self._pause_action = menu.addAction("Pause")
        self._pause_action.triggered.connect(self._on_pause_resume)
        self._pause_action.setEnabled(False)
        menu.addSeparator()
        exit_action = menu.addAction("Exit")
        exit_action.triggered.connect(self._on_exit)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_activated)
        self.tray_icon.show()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._on_show()

    def _on_show(self) -> None:
        self._main_window.showNormal()
        self._main_window.raise_()
        self._main_window.activateWindow()

    def _on_pause_resume(self) -> None:
        snapshot = self._controller.get_snapshot()
        if snapshot.ready and snapshot.state is FocusState.PAUSED:
            self._controller.resume()
        else:
            self._controller.pause()

    def _on_exit(self) -> None:
        self._main_window.request_exit()

    def refresh(self) -> None:
        snapshot = self._controller.get_snapshot()
        state = snapshot.state if snapshot.ready else None
        self.tray_icon.setIcon(_make_status_icon(_STATE_COLORS.get(state, _STATE_COLORS[None])))
        label = "Starting…" if not snapshot.ready else state.value.title()
        self.tray_icon.setToolTip(f"AI Focus Tracker - {label}")
        self._status_action.setText(f"Status: {label}")
        self._pause_action.setText("Resume" if state is FocusState.PAUSED else "Pause")
        self._pause_action.setEnabled(snapshot.ready)
