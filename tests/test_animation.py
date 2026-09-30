"""The animation engine, which is where the bugs that never show up in a
screenshot live: a pose that never reverts, blinking that stops, a transition
that never finishes."""

from __future__ import annotations

import random

import pytest

from wizard.character.animation import (
    BLINK_EVERY,
    TRANSITION_S,
    Animator,
    ease_in_out,
    ease_out_cubic,
    still_frame,
)
from wizard.character.emote import Emote, duration_of, emote_for, is_one_shot
from wizard.mood import Mood


def run(animator: Animator, seconds: float, step: float = 1 / 30):
    """Advance in realistic steps and return the last frame."""
    frame = None
    elapsed = 0.0
    while elapsed < seconds:
        frame = animator.advance(step)
        elapsed += step
    return frame


# -- the emote vocabulary ---------------------------------------------------


def test_every_mood_maps_to_a_pose():
    # A new Mood with no pose would silently draw as IDLE, so the mapping is
    # exhaustive by test rather than by a dict.get default.
    for mood in Mood:
        assert isinstance(emote_for(mood), Emote)


def test_a_waiting_mood_gets_its_own_pose():
    # The one state that needs the user to act must not look like resting.
    assert emote_for(Mood.WAITING) is Emote.WAITING_APPROVAL
    assert emote_for(Mood.CALM) is Emote.IDLE


def test_one_shots_have_a_duration_and_states_do_not():
    for emote in Emote:
        if is_one_shot(emote):
            assert duration_of(emote) > 0.0
        else:
            assert duration_of(emote) == 0.0


# -- transitions ------------------------------------------------------------


def test_starts_settled_on_its_base_pose():
    frame = Animator(base=Emote.BUSY).advance(0.0)

    assert frame.emote is Emote.BUSY
    assert frame.previous is None
    assert frame.blend == pytest.approx(1.0)


def test_changing_the_base_blends_from_the_old_pose():
    animator = Animator(base=Emote.IDLE)
    animator.advance(0.1)
    animator.set_base(Emote.STRESSED)

    frame = animator.advance(TRANSITION_S / 2)
    assert frame.emote is Emote.STRESSED
    assert frame.previous is Emote.IDLE
    assert 0.0 < frame.blend < 1.0


def test_a_transition_always_finishes():
    animator = Animator(base=Emote.IDLE)
    animator.set_base(Emote.WORKING)

    frame = run(animator, TRANSITION_S * 3)

    assert frame.blend == pytest.approx(1.0)
    assert frame.previous is None


def test_setting_the_same_base_twice_does_not_restart_anything():
    animator = Animator(base=Emote.IDLE)
    run(animator, 1.0)
    animator.set_base(Emote.IDLE)
    frame = animator.advance(0.0)

    assert frame.previous is None
    assert frame.blend == pytest.approx(1.0)


def test_the_breathing_clock_survives_a_pose_change():
    animator = Animator(base=Emote.IDLE)
    run(animator, 2.0)
    animator.set_base(Emote.BUSY)
    frame = animator.advance(0.1)

    # `time` restarts with the pose so each pose loops from its own zero, but
    # `total_time` must not: the bob would visibly jump on every mood change.
    assert frame.time < 0.5
    assert frame.total_time > 2.0


# -- one-shot poses ---------------------------------------------------------


def test_a_one_shot_reverts_to_the_resting_pose():
    animator = Animator(base=Emote.IDLE)
    animator.play(Emote.GREETING)

    assert animator.advance(0.0).emote is Emote.GREETING
    frame = run(animator, duration_of(Emote.GREETING) + 0.5)

    assert frame.emote is Emote.IDLE
    assert not animator.playing_one_shot


def test_a_mood_change_during_a_one_shot_lands_after_it():
    animator = Animator(base=Emote.IDLE)
    animator.play(Emote.GREETING)
    run(animator, 0.3)

    animator.set_base(Emote.WORKING)
    # Still waving: cutting an animation off halfway reads as a glitch.
    assert animator.current is Emote.GREETING

    frame = run(animator, duration_of(Emote.GREETING) + 0.5)
    assert frame.emote is Emote.WORKING


def test_a_state_pose_stays_until_released():
    animator = Animator(base=Emote.IDLE)
    animator.play(Emote.LISTENING)

    assert run(animator, 30.0).emote is Emote.LISTENING
    animator.release()
    assert run(animator, TRANSITION_S * 2).emote is Emote.IDLE


# -- blinking ---------------------------------------------------------------


def test_he_blinks():
    animator = Animator(base=Emote.IDLE, rng=random.Random(1))
    openness = [animator.advance(1 / 60).eye_open for _ in range(60 * 20)]

    assert min(openness) < 0.2, "never blinked over twenty seconds"
    assert max(openness) == pytest.approx(1.0)


def test_blinking_keeps_happening():
    # A blink scheduler that forgets to re-arm still passes a "does he blink"
    # test, because the first blink works.
    animator = Animator(base=Emote.IDLE, rng=random.Random(7))
    halves = []
    for _ in range(2):
        openness = [animator.advance(1 / 60).eye_open for _ in range(60 * 15)]
        halves.append(min(openness))

    assert all(low < 0.2 for low in halves)


def test_eyes_are_never_outside_zero_to_one():
    animator = Animator(base=Emote.IDLE, rng=random.Random(3))
    for _ in range(60 * 30):
        assert 0.0 <= animator.advance(1 / 60).eye_open <= 1.0


def test_a_long_step_does_not_break_the_blink():
    # Frame pacing is adaptive and the app can be suspended; a 4-second step is
    # a real thing that happens.
    animator = Animator(base=Emote.IDLE, rng=random.Random(5))
    for _ in range(20):
        frame = animator.advance(4.0)
        assert 0.0 <= frame.eye_open <= 1.0


# -- dozing off ------------------------------------------------------------


def test_he_falls_asleep_when_nothing_happens():
    animator = Animator(base=Emote.IDLE, sleep_after=10.0)

    assert run(animator, 12.0).emote is Emote.SLEEPING
    assert animator.asleep


def test_he_wakes_on_a_hover():
    animator = Animator(base=Emote.IDLE, sleep_after=10.0)
    run(animator, 12.0)

    animator.set_hovered(True)
    frame = run(animator, TRANSITION_S * 2)

    assert frame.emote is Emote.IDLE
    assert not animator.asleep


def test_he_does_not_fall_asleep_while_claude_is_working():
    animator = Animator(base=Emote.WORKING, sleep_after=10.0)

    assert run(animator, 20.0).emote is Emote.WORKING
    assert not animator.asleep


def test_waking_up_lands_on_the_current_mood_not_the_old_one():
    animator = Animator(base=Emote.IDLE, sleep_after=10.0)
    run(animator, 12.0)
    animator.set_base(Emote.STRESSED)

    frame = run(animator, TRANSITION_S * 2)
    assert frame.emote is Emote.STRESSED


def test_sleeping_can_be_switched_off():
    animator = Animator(base=Emote.IDLE, sleep_after=0.0)

    assert run(animator, 60.0).emote is Emote.IDLE


def test_eyes_stay_shut_while_asleep():
    animator = Animator(base=Emote.IDLE, sleep_after=5.0, rng=random.Random(2))
    run(animator, 8.0)

    assert animator.advance(1.0).eye_open == pytest.approx(0.0)


# -- inputs ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [((0.0, 0.0), (0.0, 0.0)), ((2.0, -9.0), (1.0, -1.0)), ((-0.5, 0.25), (-0.5, 0.25))],
)
def test_look_is_clamped_to_the_unit_square(given, expected):
    animator = Animator()
    animator.set_look(*given)

    assert animator.advance(0.0).look == pytest.approx(expected)


@pytest.mark.parametrize(("given", "expected"), [(-1.0, 0.0), (0.4, 0.4), (3.0, 1.0)])
def test_microphone_level_is_clamped(given, expected):
    animator = Animator()
    animator.set_level(given)

    assert animator.advance(0.0).level == pytest.approx(expected)


def test_flags_reach_the_frame():
    animator = Animator()
    animator.set_pressed(True)
    animator.set_catching(True)
    animator.set_hovered(True)

    frame = animator.advance(0.0)
    assert (frame.pressed, frame.catching, frame.hovered) == (True, True, True)


def test_time_never_runs_backwards_on_a_negative_step():
    animator = Animator()
    animator.advance(1.0)
    frame = animator.advance(-5.0)

    assert frame.total_time == pytest.approx(1.0)


# -- easing and still frames ----------------------------------------------


@pytest.mark.parametrize("easing", [ease_out_cubic, ease_in_out])
def test_easing_is_pinned_at_both_ends_and_clamped(easing):
    assert easing(0.0) == pytest.approx(0.0)
    assert easing(1.0) == pytest.approx(1.0)
    assert easing(-3.0) == pytest.approx(0.0)
    assert easing(9.0) == pytest.approx(1.0)
    assert 0.0 < easing(0.5) < 1.0


def test_a_still_frame_is_settled():
    frame = still_frame(Emote.SUCCESS, shadow=False, feature_scale=1.45)

    assert frame.emote is Emote.SUCCESS
    assert frame.previous is None
    assert frame.blend == pytest.approx(1.0)
    assert frame.shadow is False
    assert frame.feature_scale == pytest.approx(1.45)


def test_blink_interval_is_sane():
    low, high = BLINK_EVERY
    assert 0.5 < low < high < 30.0
