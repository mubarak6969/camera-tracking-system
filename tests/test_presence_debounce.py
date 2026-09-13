from __future__ import annotations

from focus_tracker.camera.debounce import PresenceDebouncer


def test_initial_state_is_returned_before_any_observation():
    debouncer = PresenceDebouncer(confirm_frames=3, initial_state=True)
    assert debouncer.state is True


def test_single_disagreeing_frame_does_not_flip_state():
    debouncer = PresenceDebouncer(confirm_frames=3, initial_state=True)
    result = debouncer.observe(False)
    assert result is True
    assert debouncer.state is True


def test_flips_after_confirm_frames_consecutive_disagreements():
    debouncer = PresenceDebouncer(confirm_frames=3, initial_state=True)
    assert debouncer.observe(False) is True
    assert debouncer.observe(False) is True
    assert debouncer.observe(False) is False  # third consecutive disagreement


def test_an_agreeing_frame_resets_the_disagreeing_streak():
    debouncer = PresenceDebouncer(confirm_frames=3, initial_state=True)
    debouncer.observe(False)
    debouncer.observe(False)
    debouncer.observe(True)  # agrees with current state - resets the streak
    assert debouncer.observe(False) is True
    assert debouncer.observe(False) is True
    assert debouncer.observe(False) is False


def test_debounces_negative_to_positive_transition_symmetrically():
    debouncer = PresenceDebouncer(confirm_frames=2, initial_state=False)
    assert debouncer.observe(True) is False
    assert debouncer.observe(True) is True


def test_confirm_frames_of_one_flips_immediately():
    debouncer = PresenceDebouncer(confirm_frames=1, initial_state=True)
    assert debouncer.observe(False) is False


def test_confirm_frames_must_be_at_least_one():
    import pytest

    with pytest.raises(ValueError):
        PresenceDebouncer(confirm_frames=0)
