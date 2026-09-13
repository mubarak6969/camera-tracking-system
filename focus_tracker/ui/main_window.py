"""The main application window.

Holds no business logic of its own - every value it displays comes from
FocusTrackerController.get_snapshot() (polled on a plain QTimer, since the
work-time display changes continuously and isn't itself a discrete event)
or from the controller's alert_entered/error_occurred/camera_status_changed
signals. Nothing here touches OpenCV, pynput, or SQLite directly.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from focus_tracker.app.controller import FocusTrackerController
from focus_tracker.config.settings import AppConfig
from focus_tracker.core.states import FocusState
from focus_tracker.ui.alert_dialog import InactivityAlertDialog
from focus_tracker.ui.settings_dialog import SettingsDialog
from focus_tracker.ui.tray import TrayController

_STATE_LABELS = {
    FocusState.WORKING: "Working",
    FocusState.INACTIVE: "Inactive",
    FocusState.ALERT: "Alert - are you still working?",
    FocusState.PAUSED: "Paused",
    FocusState.AWAY: "Away",
}
_PAUSABLE_STATES = (FocusState.WORKING, FocusState.INACTIVE, FocusState.ALERT)
_POLL_INTERVAL_MS = 500
_HISTORY_REFRESH_EVERY_N_TICKS = 20  # ~10s at the 500ms poll interval

_PRIVACY_TEXT = (
    "<b>Privacy</b><br><br>"
    "&bull; Camera frames are processed locally and are never saved, streamed, or uploaded.<br>"
    "&bull; No images or video are ever written to disk.<br>"
    "&bull; No typed text or key names are recorded - only \"activity happened, at this time.\"<br>"
    "&bull; No mouse coordinates are recorded.<br>"
    "&bull; All session data is stored locally on this PC in a SQLite database.<br>"
    "&bull; Nothing is sent to the cloud or to any third party."
)


def _format_duration(seconds: float) -> str:
    total_seconds = int(max(seconds, 0))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class MainWindow(QMainWindow):
    def __init__(self, controller: FocusTrackerController, config: AppConfig) -> None:
        super().__init__()
        self._controller = controller
        self._config = config
        self._alert_dialog: Optional[InactivityAlertDialog] = None
        self._really_quit = False
        self._banner_category: Optional[str] = None
        self._tick_count = 0

        self.setWindowTitle("AI Focus Tracker")
        self.resize(440, 560)

        self._banner_label = QLabel("")
        self._banner_label.setStyleSheet("background: #fff3cd; color: #664d03; padding: 6px;")
        self._banner_label.setWordWrap(True)
        self._banner_label.hide()

        self._status_label = QLabel("Starting…")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet("font-size: 16px; font-weight: 600;")

        self._timer_label = QLabel("00:00:00")
        self._timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._timer_label.setStyleSheet("font-size: 36px; font-weight: 600;")

        self._today_label = QLabel("Today: 00:00:00")
        self._start_label = QLabel("Session started: -")

        self._pause_button = QPushButton("Pause")
        self._pause_button.setEnabled(False)
        self._pause_button.clicked.connect(self._on_pause_resume_clicked)

        settings_button = QPushButton("Settings…")
        settings_button.clicked.connect(self._open_settings)
        privacy_button = QPushButton("Privacy")
        privacy_button.clicked.connect(self._show_privacy)

        buttons_row = QHBoxLayout()
        buttons_row.addWidget(self._pause_button)
        buttons_row.addWidget(settings_button)
        buttons_row.addWidget(privacy_button)

        self._history_table = QTableWidget(0, 4)
        self._history_table.setHorizontalHeaderLabels(["Start", "End", "Duration", "Reason"])
        self._history_table.horizontalHeader().setStretchLastSection(True)
        self._history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        privacy_note = QLabel(
            "🔒 Camera processed locally · nothing recorded but timestamps and state"
        )
        privacy_note.setStyleSheet("color: #666; font-size: 11px;")
        privacy_note.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(self._banner_label)
        layout.addWidget(self._status_label)
        layout.addWidget(self._timer_label)
        layout.addWidget(self._today_label)
        layout.addWidget(self._start_label)
        layout.addLayout(buttons_row)
        layout.addWidget(QLabel("Recent sessions:"))
        layout.addWidget(self._history_table)
        layout.addWidget(privacy_note)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self._build_menu()

        self._tray = TrayController(self, self._controller, self)

        self._controller.alert_entered.connect(self._on_alert_entered)
        self._controller.error_occurred.connect(self._on_error)
        self._controller.camera_status_changed.connect(self._on_camera_status_changed)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._refresh)
        self._poll_timer.start(_POLL_INTERVAL_MS)

        self._refresh_history()
        self._refresh()

    # -- Menu / window lifecycle ------------------------------------------

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        settings_action = file_menu.addAction("&Settings…")
        settings_action.triggered.connect(self._open_settings)
        privacy_action = file_menu.addAction("&Privacy")
        privacy_action.triggered.connect(self._show_privacy)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.request_exit)

    def request_exit(self) -> None:
        self._really_quit = True
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._really_quit:
            event.accept()
            return
        event.ignore()
        self.hide()

    # -- Pause/Resume ------------------------------------------------------

    def _on_pause_resume_clicked(self) -> None:
        snapshot = self._controller.get_snapshot()
        if snapshot.ready and snapshot.state is FocusState.PAUSED:
            self._controller.resume()
        else:
            self._controller.pause()
        self._refresh()

    # -- Periodic refresh ---------------------------------------------------

    def _refresh(self) -> None:
        snapshot = self._controller.get_snapshot()
        self._tray.refresh()

        if not snapshot.ready:
            self._status_label.setText("Starting… waiting for camera")
            self._timer_label.setText("00:00:00")
            self._today_label.setText(f"Today: {_format_duration(snapshot.today_total_seconds)}")
            self._pause_button.setEnabled(False)
        else:
            self._status_label.setText(_STATE_LABELS.get(snapshot.state, str(snapshot.state)))
            self._timer_label.setText(_format_duration(snapshot.elapsed_work_time))
            self._today_label.setText(f"Today: {_format_duration(snapshot.today_total_seconds)}")
            if snapshot.session_start_utc is not None:
                local_start = snapshot.session_start_utc.astimezone()
                self._start_label.setText(f"Session started: {local_start.strftime('%H:%M:%S')}")
            self._pause_button.setEnabled(
                snapshot.state in _PAUSABLE_STATES or snapshot.state is FocusState.PAUSED
            )
            self._pause_button.setText("Resume" if snapshot.state is FocusState.PAUSED else "Pause")

        self._tick_count += 1
        if self._tick_count % _HISTORY_REFRESH_EVERY_N_TICKS == 0:
            self._refresh_history()

    def _refresh_history(self) -> None:
        sessions = self._controller.get_recent_sessions(limit=20)
        self._history_table.setRowCount(len(sessions))
        for row, session in enumerate(sessions):
            start = session.started_at_utc.replace("T", " ")[:19]
            end = session.ended_at_utc.replace("T", " ")[:19] if session.ended_at_utc else "(in progress)"
            duration = _format_duration(session.total_work_seconds)
            reason = session.end_reason or "-"
            for col, value in enumerate((start, end, duration, reason)):
                self._history_table.setItem(row, col, QTableWidgetItem(value))

    # -- Alert dialog --------------------------------------------------------

    def _on_alert_entered(self) -> None:
        if self._alert_dialog is not None:
            return
        dialog = InactivityAlertDialog(self)
        dialog.continue_clicked.connect(self._on_alert_continue)
        dialog.pause_clicked.connect(self._on_alert_pause)
        self._alert_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_alert_continue(self) -> None:
        self._controller.continue_working()
        self._close_alert_dialog()

    def _on_alert_pause(self) -> None:
        self._controller.pause()
        self._close_alert_dialog()

    def _close_alert_dialog(self) -> None:
        if self._alert_dialog is not None:
            dialog = self._alert_dialog
            self._alert_dialog = None
            dialog.mark_resolved()
            dialog.close()

    # -- Errors / camera status ----------------------------------------------

    def _on_error(self, category: str, message: str) -> None:
        if not message:
            return
        self._banner_category = category
        self._banner_label.setText(message)
        self._banner_label.show()

    def _on_camera_status_changed(self, available: bool) -> None:
        if available and self._banner_category == "camera":
            self._banner_label.hide()
            self._banner_category = None

    # -- Settings / privacy ---------------------------------------------------

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self._config, self)
        dialog.exec()

    def _show_privacy(self) -> None:
        QMessageBox.information(self, "Privacy", _PRIVACY_TEXT)
