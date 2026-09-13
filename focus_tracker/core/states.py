"""Shared types for the focus state machine.

Kept separate from state_machine.py so other modules (the timer, the
session orchestrator, tests) can import just the vocabulary - the enum,
the event, and the error type - without pulling in the transition logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FocusState(Enum):
    WORKING = "WORKING"
    INACTIVE = "INACTIVE"
    ALERT = "ALERT"
    PAUSED = "PAUSED"
    AWAY = "AWAY"


class InvalidTransitionError(RuntimeError):
    """Raised when an explicit action (pause/resume/continue) is requested
    from a state it does not apply to. Passive sensor signals (activity,
    idle, presence) never raise this - they are idempotent no-ops instead,
    since a camera or input device may repeat the same signal many times.
    """


@dataclass(frozen=True)
class StateChangeEvent:
    from_state: FocusState
    to_state: FocusState
    monotonic_timestamp: float
