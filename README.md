# AI Focus Tracker

A free, local-first Windows desktop app that measures focused work time
using webcam presence detection and system-wide keyboard/mouse activity.
No cloud backend, no paid APIs, no camera frames or raw input are ever
stored.

## Status

This repository currently contains only the **foundation**: the core
state machine, the work-time timer, the SQLite persistence layer, and
configuration. Webcam presence detection, keyboard/mouse monitoring, the
desktop UI, notifications, and packaging are **not implemented yet** -
they land in later phases on top of this foundation.

## Requirements

- Windows 10/11
- Python 3.11

## Setup

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

## Running the tests

```bash
.venv\Scripts\pytest
```

## Project layout

```
focus_tracker/
  config/          # central AppConfig (grace period, camera/input tuning, db path)
  core/            # state machine, work timer, and the FocusSession that wires them together
  storage/         # SQLite connection/migrations and the session repository
  camera/          # reserved for webcam presence detection (not implemented yet)
  input_monitor/   # reserved for keyboard/mouse activity monitoring (not implemented yet)
  ui/              # reserved for the PySide6 desktop UI (not implemented yet)
  notifications/   # reserved for desktop notifications/sound (not implemented yet)
tests/             # automated tests for core/ and storage/
main.py            # temporary smoke-test entry point (no UI yet)
```

## Design notes

- The state machine (`focus_tracker/core/state_machine.py`) is pure: it
  only depends on an injected clock function, never `time.sleep`, Qt,
  OpenCV, pynput, or SQLite. This is what makes it fully unit-testable
  without waiting on real timers.
- The work timer (`focus_tracker/core/timer.py`) accumulates elapsed time
  from `time.monotonic()` differences, not by incrementing a counter
  once a second, so it stays accurate regardless of how often it's
  polled.
- `focus_tracker/core/session.py`'s `FocusSession` is the only object the
  future UI/sensing layers need to talk to; it persists nothing itself -
  it just exposes an `on_state_change` hook that the app layer can wire
  to `storage/repository.py`.
- All persisted timestamps are ISO-8601 UTC strings. The monotonic clock
  used internally for elapsed-time math never reaches the database.
- No `.env` file is included: this app has no secrets, API keys, or
  external services to configure in V1, so one would be dead weight.
