# AI Focus Tracker

A free, local-first Windows desktop app that measures focused work time
using webcam presence detection and system-wide keyboard/mouse activity.
No cloud backend, no paid APIs, no network calls, no camera frames or raw
input are ever stored.

## Status

A working desktop application: PySide6 UI, system tray, a real webcam
presence worker, real keyboard/mouse activity monitoring, Windows
lock/sleep/wake detection, SQLite persistence with crash recovery, and a
Settings dialog. See "Known limitations" below for what's still rough.

## Requirements

- Windows 10/11
- Python 3.11

## Setup

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

## Running the app

```bash
.venv\Scripts\python.exe app.py
```

Closing the window minimizes it to the system tray rather than exiting -
use the tray icon's **Exit** or the window's **File > Exit** to actually
quit (which stops the camera, input hooks, and lock monitor cleanly).

## Running the tests

```bash
.venv\Scripts\pytest
```

## Building a Windows executable

```bash
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pyinstaller AIFocusTracker.spec
```

The build lands in `dist/AIFocusTracker/AIFocusTracker.exe`. It bundles
its own Python, Qt, OpenCV (including the Haar cascade data files), and
pywin32 - it does not depend on the development virtual environment or a
system Python install. See `AIFocusTracker.spec` for what's included and
why.

## Project layout

```
focus_tracker/
  config/          # AppConfig, plus config/store.py (load/save/validate user settings as JSON)
  core/            # state machine, work timer, FocusSession, and the sensor event/bridge types
  storage/         # SQLite connection/migrations and the session repository
  camera/          # webcam presence worker (OpenCV + Haar cascade + debounce)
  input_monitor/   # keyboard/mouse activity worker (pynput)
  platform_win/    # Windows lock/sleep/wake detection (pywin32), isolated from the rest of the app
  app/             # FocusTrackerController - the Qt-aware seam between core/sensing and the UI
  ui/              # PySide6 main window, tray, alert dialog, settings dialog
  notifications/   # reserved - sound alert currently lives inline in ui/alert_dialog.py via winsound
  timeutil.py      # local-calendar-day helper used for "today's total"
  concurrency.py   # PeriodicWorker - the shared background-thread scheduling primitive
tests/             # automated tests for every layer above, all hardware-independent
scripts/hardware_smoke_test.py  # manual, real-hardware verification script (not part of CI)
main.py            # original core-only smoke test from an early phase
app.py             # the real desktop entry point
AIFocusTracker.spec # PyInstaller build configuration
```

## Design notes

- The state machine (`focus_tracker/core/state_machine.py`) is pure: it
  only depends on an injected clock function, never `time.sleep`, Qt,
  OpenCV, pynput, or SQLite - fully unit-testable without real timers or
  hardware.
- The work timer (`focus_tracker/core/timer.py`) accumulates elapsed time
  from `time.monotonic()` differences, never by incrementing a counter
  once a second, so it stays accurate regardless of how often it's polled.
- `SensorBridge` (`focus_tracker/core/sensor_bridge.py`) is the only piece
  that translates camera/input/lock events into FocusSession calls; a
  manually paused session is never overridden by a camera presence
  reading (see the comments there for the exact rule), while a lock- or
  sleep-induced pause still forces AWAY on unlock/wake so stale presence
  is never trusted.
- `FocusTrackerController` (`focus_tracker/app/controller.py`) is the only
  Qt-aware seam - it owns every worker and the real FocusSession, uses a
  single `RLock` to serialize all camera/input/poll/lock-monitor thread
  callbacks, and short-circuits every callback the instant `shutdown()`
  begins so no worker can act on a session/database mid-teardown.
- All persisted timestamps are ISO-8601 UTC strings; "today's total" is
  computed from the user's local calendar day (`focus_tracker/timeutil.py`)
  and converted to a UTC boundary for the query. The monotonic clock used
  internally for elapsed-time math never reaches the database.
- A session interrupted by a crash or a forced kill is reconciled on the
  next launch (`FocusTrackerController._recover_stale_sessions()`): its
  last known total is preserved and it is marked `"interrupted"` rather
  than left dangling forever as `"in_progress"`.
- No `.env` file is included: this app has no secrets, API keys, or
  external services to configure in V1, so one would be dead weight.

## Privacy

- **Camera frames are processed entirely locally**, in memory, one at a
  time - only a `present: bool` ever leaves the camera worker. No frame,
  image, or video is ever written to disk, streamed, or uploaded.
- **No face recognition or identity detection** of any kind - only "is a
  face-shaped region present," using OpenCV's bundled Haar cascade.
- **Keyboard/mouse monitoring records only that activity occurred and
  when.** No key names, typed text, mouse coordinates, application/window
  titles, or screenshots are ever captured or stored - `ActivityEvent`
  (`focus_tracker/core/sensor_events.py`) has exactly one field,
  `monotonic_timestamp`, so there is nothing else it could carry.
- **All data stays on this PC**, in a local SQLite database (see
  `focus_tracker/config/settings.py` for its path). Nothing is sent to
  the cloud or to any third party, and the app makes no network calls.
- **What's stored:** session start/end times, total focused seconds, and
  a log of state transitions (e.g. `WORKING -> INACTIVE` with a
  timestamp) - never anything about *what* you were doing, only *whether*
  you were present and active.
- The database file has the same access permissions as any other file in
  your Windows user profile - only your own account can read it by
  default.

## Known limitations

- Settings changes require restarting the app - there's no live
  hot-reload of a running camera worker or an in-progress session's
  grace period.
- A session interrupted by a crash is finalized with whatever total was
  last checkpointed (checkpoints run every 30 seconds), so at most the
  last 30 seconds of a crashed session can be lost - never the whole
  session.
- If the camera is never available at all, the app does not force a
  fallback "Working" state - it stays in "Starting…" indefinitely and
  reports the camera as unavailable, since counting time without
  confirmed presence would be worse than not counting it.
