"""Windows-only OS integration, isolated from the rest of the app.

Nothing outside this package imports pywin32. Consumers only ever see
focus_tracker.core.lock_events.SessionLockEvent objects, delivered through
a start()/stop() object shaped like WindowsSessionMonitor.
"""
from focus_tracker.platform_win.session_monitor import WindowsSessionMonitor

__all__ = ["WindowsSessionMonitor"]
