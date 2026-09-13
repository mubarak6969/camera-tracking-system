"""Shared test fixtures.

Most importantly: a controllable fake clock, so tests can exercise the
2-minute grace period (and any other time-based behavior) by advancing a
number instantly instead of calling time.sleep().
"""
from __future__ import annotations

import pytest


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()
