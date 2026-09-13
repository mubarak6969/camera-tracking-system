"""AI Focus Tracker - desktop application entry point.

Run with:
    .venv\\Scripts\\python.exe app.py

This is the real GUI entry point; main.py remains the original core-only
smoke test from an earlier phase and is left untouched.
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from focus_tracker.app.controller import FocusTrackerController
from focus_tracker.config.settings import AppConfig
from focus_tracker.config.store import load_config
from focus_tracker.ui.main_window import MainWindow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> int:
    base_config = AppConfig()
    config = load_config(base_config)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # closing the window minimizes to tray instead of quitting

    controller = FocusTrackerController(config)
    window = MainWindow(controller, config)
    window.show()

    controller.start()
    app.aboutToQuit.connect(controller.shutdown)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
