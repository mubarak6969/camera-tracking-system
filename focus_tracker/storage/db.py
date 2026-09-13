"""SQLite connection management and schema migrations.

Timestamp strategy: every timestamp persisted by this layer is an
ISO-8601 string in UTC (e.g. "2026-09-13T10:15:00+00:00"). The
monotonic clock used by core/timer.py and core/state_machine.py for
elapsed-time math never reaches this module - callers must convert to a
UTC `datetime` first (see core/session.py's PersistableTransition).

Migrations are tracked with SQLite's built-in `PRAGMA user_version`
rather than a hand-rolled version table, since it already does exactly
what we need with no extra schema.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Union

_MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at_utc TEXT NOT NULL,
        ended_at_utc TEXT,
        total_work_seconds REAL NOT NULL DEFAULT 0,
        end_reason TEXT
    );

    CREATE TABLE state_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        from_state TEXT NOT NULL,
        to_state TEXT NOT NULL,
        occurred_at_utc TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );

    CREATE INDEX idx_state_events_session_id ON state_events(session_id);
    CREATE INDEX idx_sessions_started_at ON sessions(started_at_utc);
    """,
)


class StorageError(RuntimeError):
    """Wraps sqlite3 errors so callers only ever need to catch one
    exception type from this layer."""


class Database:
    def __init__(self, path: Union[str, Path]) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # The controller's camera/input/poll/checkpoint threads can all reach
        # this same connection. check_same_thread=False lets any thread use
        # it, but does not by itself guarantee two threads never interleave
        # statements on it - this lock is what actually serializes that,
        # rather than relying on assumptions about how the local SQLite
        # build was compiled.
        self.lock = threading.RLock()
        try:
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._migrate()
        except sqlite3.Error as exc:
            raise StorageError(f"failed to open database at {self._path}: {exc}") from exc

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def _migrate(self) -> None:
        current_version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        for version, script in enumerate(_MIGRATIONS, start=1):
            if version <= current_version:
                continue
            try:
                with self._conn:
                    self._conn.executescript(script)
                    self._conn.execute(f"PRAGMA user_version = {version}")
            except sqlite3.Error as exc:
                raise StorageError(f"migration {version} failed: {exc}") from exc
