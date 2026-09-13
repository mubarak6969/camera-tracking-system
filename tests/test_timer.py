from __future__ import annotations

import pytest

from focus_tracker.core.timer import SessionTimer, TimerStateError


def test_elapsed_before_start_is_zero(fake_clock):
    timer = SessionTimer(clock=fake_clock)
    assert timer.elapsed() == 0.0


def test_accumulates_while_running(fake_clock):
    timer = SessionTimer(clock=fake_clock)
    timer.start()
    fake_clock.advance(10)
    assert timer.elapsed() == 10


def test_pause_stops_accumulation(fake_clock):
    timer = SessionTimer(clock=fake_clock)
    timer.start()
    fake_clock.advance(10)
    timer.pause()
    fake_clock.advance(50)
    assert timer.elapsed() == 10


def test_resume_continues_from_where_it_left_off(fake_clock):
    timer = SessionTimer(clock=fake_clock)
    timer.start()
    fake_clock.advance(10)
    timer.pause()
    fake_clock.advance(50)
    timer.resume()
    fake_clock.advance(5)
    assert timer.elapsed() == 15


def test_repeated_pause_calls_do_not_lose_or_duplicate_time(fake_clock):
    timer = SessionTimer(clock=fake_clock)
    timer.start()
    fake_clock.advance(10)
    timer.pause()
    timer.pause()  # repeated signal - must be a no-op
    fake_clock.advance(100)
    timer.pause()
    assert timer.elapsed() == 10


def test_repeated_resume_calls_do_not_truncate_time(fake_clock):
    timer = SessionTimer(clock=fake_clock)
    timer.start()
    timer.resume()  # already counting - must not reset the segment
    fake_clock.advance(10)
    timer.resume()
    fake_clock.advance(5)
    assert timer.elapsed() == 15


def test_end_stops_accumulation_and_returns_total(fake_clock):
    timer = SessionTimer(clock=fake_clock)
    timer.start()
    fake_clock.advance(20)
    total = timer.end()
    fake_clock.advance(100)
    assert total == 20
    assert timer.elapsed() == 20


def test_start_twice_raises(fake_clock):
    timer = SessionTimer(clock=fake_clock)
    timer.start()
    with pytest.raises(TimerStateError):
        timer.start()


def test_pause_before_start_raises(fake_clock):
    timer = SessionTimer(clock=fake_clock)
    with pytest.raises(TimerStateError):
        timer.pause()


def test_resume_after_end_raises(fake_clock):
    timer = SessionTimer(clock=fake_clock)
    timer.start()
    timer.end()
    with pytest.raises(TimerStateError):
        timer.resume()


def test_end_while_paused_returns_accumulated_total_without_negative_duration(fake_clock):
    timer = SessionTimer(clock=fake_clock)
    timer.start()
    fake_clock.advance(30)
    timer.pause()
    fake_clock.advance(9999)  # a long paused gap must never leak into the total

    total = timer.end()

    assert total == pytest.approx(30)
    assert total >= 0


def test_end_called_twice_is_idempotent(fake_clock):
    timer = SessionTimer(clock=fake_clock)
    timer.start()
    fake_clock.advance(15)

    first_total = timer.end()
    fake_clock.advance(100)  # time passing after end() must never be counted
    second_total = timer.end()

    assert first_total == pytest.approx(15)
    assert second_total == pytest.approx(15)


def test_elapsed_never_goes_negative_across_many_pause_resume_cycles(fake_clock):
    timer = SessionTimer(clock=fake_clock)
    timer.start()
    for _ in range(50):
        fake_clock.advance(2)
        timer.pause()
        fake_clock.advance(3)
        timer.resume()

    assert timer.elapsed() == pytest.approx(100)  # 50 * 2s of actual counted time
    assert timer.elapsed() >= 0
