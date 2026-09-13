"""Manual hardware smoke test - NOT part of the automated test suite.

Run this only when you want to verify the real webcam and real global
keyboard/mouse hooks on this machine:

    .venv\\Scripts\\python.exe scripts\\hardware_smoke_test.py [duration_seconds]

It wires the real CameraPresenceWorker and InputActivityWorker to a real
FocusSession through SensorBridge, prints presence/activity/state changes
as they happen for a bounded duration (default 30s, or until Ctrl+C), then
shuts every worker down cleanly. It does not touch the database or any
UI - only the sensing layer and the existing core engine.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from focus_tracker.camera.presence_worker import CameraPresenceWorker
from focus_tracker.concurrency import PeriodicWorker
from focus_tracker.config.settings import AppConfig
from focus_tracker.core.sensor_bridge import SensorBridge
from focus_tracker.core.sensor_events import ActivityEvent, PresenceEvent
from focus_tracker.core.session import FocusSession
from focus_tracker.input_monitor.activity_worker import InputActivityWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main(duration_seconds: float = 30.0) -> None:
    config = AppConfig()
    session = FocusSession(grace_period_seconds=config.inactivity_grace_period_seconds)
    session.start()
    bridge = SensorBridge(session, idle_threshold_seconds=config.activity_idle_threshold_seconds)

    def on_presence(event: PresenceEvent) -> None:
        print(f"[camera]  present={event.present}")
        bridge.handle_presence(event)

    def on_activity(event: ActivityEvent) -> None:
        print(f"[input]   activity at t={event.monotonic_timestamp:.1f}")
        bridge.handle_activity(event)

    camera = CameraPresenceWorker(
        on_presence_change=on_presence,
        sampling_interval_seconds=config.camera_sampling_interval_seconds,
        confirm_frames=config.presence_debounce_frames,
        camera_index=config.camera_index,
        max_retry_backoff_seconds=config.camera_max_retry_backoff_seconds,
    )
    input_monitor = InputActivityWorker(
        on_activity=on_activity,
        collapse_interval_seconds=config.input_event_collapse_interval_seconds,
        on_error=lambda exc: print(f"[input]   listener error: {exc}"),
    )
    poller = PeriodicWorker(config.sensor_poll_interval_seconds, bridge.poll, name="SensorPoll")

    print(f"Starting camera, input monitor, and poller for {duration_seconds:.0f}s (Ctrl+C to stop early).")
    camera.start()
    input_monitor.start()
    poller.start()

    last_state = session.state
    print(f"[state]   initial: {last_state.value}")
    try:
        end_at = time.monotonic() + duration_seconds
        while time.monotonic() < end_at:
            if session.state != last_state:
                print(f"[state]   {last_state.value} -> {session.state.value}")
                last_state = session.state
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Interrupted - shutting down.")
    finally:
        poller.stop()
        input_monitor.stop()
        camera.stop()
        total = session.end()
        print(f"Done. Elapsed work time recorded: {total:.1f}s. All workers stopped.")


if __name__ == "__main__":
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    main(duration)
