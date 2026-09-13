"""Session and state-event persistence.

This is the only module that turns FocusSession's transitions and
lifecycle calls into SQL. It knows nothing about the state machine, the
timer, or the UI - it just stores what it is given, in a transaction per
call so a crash mid-write can never leave a half-written row behind.

Never store camera frames, images, raw keyboard events, mouse
coordinates, or key contents here - only state names and timestamps.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from focus_tracker.storage.db import Database, StorageError


@dataclass(frozen=True)
class SessionRecord:
    id: int
    started_at_utc: str
    ended_at_utc: Optional[str]
    total_work_seconds: float
    end_reason: Optional[str]


@dataclass(frozen=True)
class StateEventRecord:
    id: int
    session_id: int
    from_state: str
    to_state: str
    occurred_at_utc: str


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create_session(self, started_at: Optional[datetime] = None) -> int:
        started_at = started_at or datetime.now(timezone.utc)
        try:
            with self._db.connection:
                cursor = self._db.connection.execute(
                    "INSERT INTO sessions (started_at_utc, total_work_seconds) VALUES (?, 0)",
                    (started_at.isoformat(),),
                )
                return int(cursor.lastrowid)
        except sqlite3.Error as exc:
            raise StorageError(f"failed to create session: {exc}") from exc

    def record_state_event(
        self,
        session_id: int,
        from_state: str,
        to_state: str,
        occurred_at: Optional[datetime] = None,
    ) -> None:
        occurred_at = occurred_at or datetime.now(timezone.utc)
        try:
            with self._db.connection:
                self._db.connection.execute(
                    "INSERT INTO state_events (session_id, from_state, to_state, occurred_at_utc) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, from_state, to_state, occurred_at.isoformat()),
                )
        except sqlite3.Error as exc:
            raise StorageError(f"failed to record state event: {exc}") from exc

    def end_session(
        self,
        session_id: int,
        total_work_seconds: float,
        end_reason: str,
        ended_at: Optional[datetime] = None,
    ) -> None:
        ended_at = ended_at or datetime.now(timezone.utc)
        try:
            with self._db.connection:
                self._db.connection.execute(
                    "UPDATE sessions SET ended_at_utc = ?, total_work_seconds = ?, end_reason = ? "
                    "WHERE id = ?",
                    (ended_at.isoformat(), total_work_seconds, end_reason, session_id),
                )
        except sqlite3.Error as exc:
            raise StorageError(f"failed to end session: {exc}") from exc

    def get_session(self, session_id: int) -> Optional[SessionRecord]:
        try:
            row = self._db.connection.execute(
                "SELECT id, started_at_utc, ended_at_utc, total_work_seconds, end_reason "
                "FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(f"failed to fetch session {session_id}: {exc}") from exc
        return SessionRecord(**dict(row)) if row is not None else None

    def list_state_events(self, session_id: int) -> list[StateEventRecord]:
        try:
            rows = self._db.connection.execute(
                "SELECT id, session_id, from_state, to_state, occurred_at_utc "
                "FROM state_events WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"failed to list state events for session {session_id}: {exc}") from exc
        return [StateEventRecord(**dict(row)) for row in rows]

    def list_recent_sessions(self, limit: int = 20) -> list[SessionRecord]:
        try:
            rows = self._db.connection.execute(
                "SELECT id, started_at_utc, ended_at_utc, total_work_seconds, end_reason "
                "FROM sessions ORDER BY started_at_utc DESC LIMIT ?",
                (limit,),
            ).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"failed to list recent sessions: {exc}") from exc
        return [SessionRecord(**dict(row)) for row in rows]

    def get_total_work_seconds_since(
        self, start_utc: datetime, exclude_session_id: Optional[int] = None
    ) -> float:
        """Used to compute "today's total": sums total_work_seconds for every
        session that started at or after `start_utc`. `exclude_session_id`
        lets the caller add the still-running session's live in-memory
        elapsed time on top, instead of double-counting its last checkpoint."""
        query = "SELECT COALESCE(SUM(total_work_seconds), 0) AS total FROM sessions WHERE started_at_utc >= ?"
        params: list = [start_utc.isoformat()]
        if exclude_session_id is not None:
            query += " AND id != ?"
            params.append(exclude_session_id)
        try:
            row = self._db.connection.execute(query, params).fetchone()
        except sqlite3.Error as exc:
            raise StorageError(f"failed to sum work seconds since {start_utc}: {exc}") from exc
        return float(row["total"])
