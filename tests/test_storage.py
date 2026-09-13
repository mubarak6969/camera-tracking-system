from __future__ import annotations

from datetime import datetime, timezone

import pytest

from focus_tracker.storage.db import Database
from focus_tracker.storage.repository import SessionRepository


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def test_database_initializes_expected_tables(db):
    tables = {
        row["name"]
        for row in db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"sessions", "state_events"} <= tables


def test_foreign_keys_are_enabled(db):
    assert db.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_wal_mode_is_enabled(db):
    assert db.connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_expected_indexes_exist(db):
    indexes = {
        row["name"]
        for row in db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert {"idx_state_events_session_id", "idx_sessions_started_at"} <= indexes


def test_create_and_fetch_session(db):
    repo = SessionRepository(db)
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session_id = repo.create_session(started_at=started)

    record = repo.get_session(session_id)

    assert record is not None
    assert record.started_at_utc == started.isoformat()
    assert record.ended_at_utc is None
    assert record.total_work_seconds == 0


def test_record_and_list_state_events(db):
    repo = SessionRepository(db)
    session_id = repo.create_session()
    repo.record_state_event(session_id, "WORKING", "INACTIVE")
    repo.record_state_event(session_id, "INACTIVE", "ALERT")

    events = repo.list_state_events(session_id)

    assert [(e.from_state, e.to_state) for e in events] == [
        ("WORKING", "INACTIVE"),
        ("INACTIVE", "ALERT"),
    ]


def test_end_session_updates_record(db):
    repo = SessionRepository(db)
    session_id = repo.create_session()

    repo.end_session(session_id, total_work_seconds=42.5, end_reason="user_quit")
    record = repo.get_session(session_id)

    assert record.ended_at_utc is not None
    assert record.total_work_seconds == 42.5
    assert record.end_reason == "user_quit"


def test_state_events_cascade_delete_with_session(db):
    repo = SessionRepository(db)
    session_id = repo.create_session()
    repo.record_state_event(session_id, "WORKING", "INACTIVE")

    with db.connection:
        db.connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    assert repo.list_state_events(session_id) == []


def test_get_missing_session_returns_none(db):
    repo = SessionRepository(db)
    assert repo.get_session(999) is None


def test_database_creates_parent_directory(tmp_path):
    nested_path = tmp_path / "nested" / "dir" / "focus.db"
    database = Database(nested_path)
    try:
        assert nested_path.exists()
    finally:
        database.close()
