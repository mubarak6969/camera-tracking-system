"""Turns noisy, frame-by-frame face-detection results into a stable
presence signal.

A single missed or spurious frame (blink, brief occlusion, lighting
flicker) must not flip the whole session to AWAY. `PresenceDebouncer`
only accepts a new state once it has seen `confirm_frames` consecutive
observations that disagree with the current state - mirroring the same
idempotency principle used throughout core: noisy repeated signals should
never corrupt state on their own.
"""
from __future__ import annotations


class PresenceDebouncer:
    def __init__(self, confirm_frames: int = 3, initial_state: bool = True) -> None:
        if confirm_frames < 1:
            raise ValueError("confirm_frames must be at least 1")
        self._confirm_frames = confirm_frames
        self._state = initial_state
        self._disagreeing_streak = 0

    @property
    def state(self) -> bool:
        return self._state

    def observe(self, raw_present: bool) -> bool:
        """Feed one raw observation; returns the debounced state (which may
        or may not have changed as a result of this observation)."""
        if raw_present == self._state:
            self._disagreeing_streak = 0
            return self._state

        self._disagreeing_streak += 1
        if self._disagreeing_streak >= self._confirm_frames:
            self._state = raw_present
            self._disagreeing_streak = 0
        return self._state
