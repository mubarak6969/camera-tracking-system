"""Windows lock/unlock and sleep/wake detection.

The application must stop counting work while the machine is locked or
asleep, and must not trust stale camera state on return - see
core/sensor_bridge.py's handle_lock_event() for that policy. This module
only detects the four underlying OS events and reports them.

Implemented with pywin32 rather than hand-rolled ctypes: creating a
message-only window and handling WM_WTSSESSION_CHANGE / WM_POWERBROADCAST
correctly by hand is one of the more error-prone corners of the raw Win32
API (wrong struct layouts fail silently or crash), and pywin32 is the
well-tested standard tool for exactly this - reliability matters more here
than avoiding one extra Windows-only dependency, and it is isolated to
this single file. Everything runs on its own background thread with its
own message pump, so it never touches whatever UI thread exists later.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from focus_tracker.core.lock_events import SessionLockEvent, SessionLockEventKind

logger = logging.getLogger(__name__)

_WM_WTSSESSION_CHANGE = 0x02B1
_WTS_SESSION_LOCK = 0x7
_WTS_SESSION_UNLOCK = 0x8


class SessionMonitorUnavailableError(RuntimeError):
    """Raised when pywin32 or the Win32 session-notification APIs are not
    available. Callers should treat this as "no lock/sleep detection on
    this machine" rather than a fatal error."""


class WindowsSessionMonitor:
    def __init__(
        self,
        on_event: Callable[[SessionLockEvent], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_event = on_event
        self._clock = clock
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._hwnd: Optional[int] = None
        self._start_error: Optional[BaseException] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._ready.clear()
        self._start_error = None
        self._thread = threading.Thread(target=self._run, name="WindowsSessionMonitor", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)
        if self._start_error is not None:
            self._thread = None
            raise SessionMonitorUnavailableError(str(self._start_error)) from self._start_error

    def stop(self) -> None:
        if self._thread is None:
            return
        if self._hwnd is not None:
            try:
                import win32api
                import win32con

                win32api.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                logger.exception("WindowsSessionMonitor: failed to post WM_CLOSE")
        self._thread.join(timeout=5.0)
        self._thread = None

    def _run(self) -> None:
        try:
            import win32con
            import win32gui
            import win32ts
        except Exception as exc:  # pywin32 not installed/importable
            self._start_error = exc
            self._ready.set()
            return

        try:
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self._wndproc_factory(win32con, win32gui)
            wc.lpszClassName = "AIFocusTrackerSessionMonitor"
            wc.hInstance = win32gui.GetModuleHandle(None)
            class_atom = win32gui.RegisterClass(wc)
            hwnd = win32gui.CreateWindow(
                class_atom, wc.lpszClassName, 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None
            )
            self._hwnd = hwnd
            try:
                win32ts.WTSRegisterSessionNotification(hwnd, win32ts.NOTIFY_FOR_THIS_SESSION)
            except Exception:
                logger.warning(
                    "WindowsSessionMonitor: WTSRegisterSessionNotification failed - "
                    "lock/unlock detection disabled, sleep/wake still active"
                )
        except Exception as exc:
            self._start_error = exc
            self._ready.set()
            return

        self._ready.set()
        try:
            win32gui.PumpMessages()
        finally:
            try:
                win32ts.WTSUnRegisterSessionNotification(hwnd)
            except Exception:
                pass
            try:
                win32gui.DestroyWindow(hwnd)
                win32gui.UnregisterClass(class_atom, wc.hInstance)
            except Exception:
                pass
            self._hwnd = None

    def _wndproc_factory(self, win32con, win32gui):
        def _wndproc(hwnd, msg, wparam, lparam):
            if msg == win32con.WM_CLOSE:
                win32gui.PostQuitMessage(0)
                return 0
            if msg == _WM_WTSSESSION_CHANGE:
                if wparam == _WTS_SESSION_LOCK:
                    self._emit(SessionLockEventKind.LOCKED)
                elif wparam == _WTS_SESSION_UNLOCK:
                    self._emit(SessionLockEventKind.UNLOCKED)
            elif msg == win32con.WM_POWERBROADCAST:
                if wparam == win32con.PBT_APMSUSPEND:
                    self._emit(SessionLockEventKind.SLEEP)
                elif wparam in (win32con.PBT_APMRESUMEAUTOMATIC, win32con.PBT_APMRESUMESUSPEND):
                    self._emit(SessionLockEventKind.WAKE)
            return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

        return _wndproc

    def _emit(self, kind: SessionLockEventKind) -> None:
        try:
            self._on_event(SessionLockEvent(kind=kind, monotonic_timestamp=self._clock()))
        except Exception:
            logger.exception("WindowsSessionMonitor: on_event callback raised")
