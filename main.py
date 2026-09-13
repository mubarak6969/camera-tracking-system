"""Temporary smoke-test entry point.

This does NOT represent the final application - there is no UI, camera,
or input monitoring wired up yet. It exists only to prove that
configuration, the state machine, the timer, and the storage layer wire
together correctly end-to-end.
"""
from __future__ import annotations

from focus_tracker.config.settings import AppConfig
from focus_tracker.core.session import FocusSession
from focus_tracker.storage.db import Database
from focus_tracker.storage.repository import SessionRepository


def main() -> None:
    config = AppConfig()
    db = Database(config.database_path)
    repository = SessionRepository(db)
    session_id = repository.create_session()

    def persist_transition(event) -> None:
        repository.record_state_event(
            session_id, event.from_state.value, event.to_state.value, event.occurred_at_utc
        )

    session = FocusSession(
        grace_period_seconds=config.inactivity_grace_period_seconds,
        on_state_change=persist_transition,
    )
    session.start()
    print(f"Database: {config.database_path}")
    print(f"Initial state: {session.state.value}")

    session.mark_idle()
    print(f"After mark_idle(): {session.state.value}")
    session.record_activity()
    print(f"After record_activity(): {session.state.value}")

    total = session.end()
    repository.end_session(session_id, total_work_seconds=total, end_reason="smoke_test")
    print(f"Elapsed work time: {total:.3f}s")
    print(f"Recorded session id: {session_id}")

    db.close()


if __name__ == "__main__":
    main()
