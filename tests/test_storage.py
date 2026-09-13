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


def test_list_recent_sessions_orders_newest_first(db):
    repo = SessionRepository(db)
    early = datetime(2026, 1, 1, tzinfo=timezone.utc)
    late = datetime(2026, 1, 2, tzinfo=timezone.utc)
    repo.create_session(started_at=early)
    repo.create_session(started_at=late)

    sessions = repo.list_recent_sessions()

    assert [s.started_at_utc for s in sessions] == [late.isoformat(), early.isoformat()]


def test_list_recent_sessions_respects_limit(db):
    repo = SessionRepository(db)
    for _ in range(5):
        repo.create_session()

    assert len(repo.list_recent_sessions(limit=2)) == 2


def test_get_total_work_seconds_since_sums_matching_sessions(db):
    repo = SessionRepository(db)
    today = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    yesterday = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    boundary = datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)

    old_id = repo.create_session(started_at=yesterday)
    repo.end_session(old_id, total_work_seconds=999, end_reason="app_exit")
    today_id = repo.create_session(started_at=today)
    repo.end_session(today_id, total_work_seconds=42, end_reason="in_progress")

    total = repo.get_total_work_seconds_since(boundary)

    assert total == pytest.approx(42)


def test_get_total_work_seconds_since_can_exclude_a_session(db):
    repo = SessionRepository(db)
    boundary = datetime(2026, 1, 1, tzinfo=timezone.utc)
    started = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    ended_id = repo.create_session(started_at=started)
    repo.end_session(ended_id, total_work_seconds=30, end_reason="app_exit")
    live_id = repo.create_session(started_at=started)
    repo.end_session(live_id, total_work_seconds=15, end_reason="in_progress")

    total = repo.get_total_work_seconds_since(boundary, exclude_session_id=live_id)

    assert total == pytest.approx(30)


def test_database_creates_parent_directory(tmp_path):
    nested_path = tmp_path / "nested" / "dir" / "focus.db"
    database = Database(nested_path)
    try:
        assert nested_path.exists()
    finally:
        database.close()
