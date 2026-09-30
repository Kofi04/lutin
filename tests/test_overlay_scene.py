"""What the overlay shows, when it goes away, and where a tutorial is up to."""

from __future__ import annotations

import pytest

from wizard.overlay.scene import DEFAULT_TTL, Highlight, Pointer, Scene, Step


def test_a_new_scene_is_empty():
    assert Scene().empty


def test_adding_a_pointer_shows_it():
    scene = Scene()
    scene.add(Pointer(10, 20, "ici"))

    assert scene.visible_items() == [Pointer(10, 20, "ici")]
    assert not scene.empty


# -- expiry -----------------------------------------------------------------


def test_annotations_expire():
    scene = Scene()
    scene.add(Pointer(0, 0), ttl=5.0)

    assert scene.tick(4.9) is False
    assert scene.visible_items()
    assert scene.tick(0.2) is True
    assert scene.empty


def test_the_default_lifetime_applies():
    scene = Scene()
    scene.add(Pointer(0, 0))
    scene.tick(DEFAULT_TTL + 0.1)

    assert scene.empty


def test_a_zero_or_missing_ttl_means_until_cleared():
    scene = Scene()
    scene.add(Pointer(0, 0), ttl=None)
    scene.add(Pointer(1, 1), ttl=0)
    scene.tick(10_000)

    assert len(scene.visible_items()) == 2


def test_each_annotation_expires_on_its_own_clock():
    scene = Scene()
    scene.add(Pointer(0, 0), ttl=2.0)
    scene.add(Pointer(1, 1), ttl=10.0)
    scene.tick(3.0)

    assert scene.visible_items() == [Pointer(1, 1)]


def test_next_expiry_reports_the_soonest():
    scene = Scene()
    scene.add(Pointer(0, 0), ttl=8.0)
    scene.add(Pointer(1, 1), ttl=3.0)

    assert scene.next_expiry() == pytest.approx(3.0)


def test_next_expiry_is_none_when_nothing_will_expire():
    scene = Scene()
    scene.add(Pointer(0, 0), ttl=None)

    assert scene.next_expiry() is None


def test_time_never_runs_backwards():
    scene = Scene()
    scene.add(Pointer(0, 0), ttl=5.0)
    scene.tick(-100)

    assert scene.visible_items()


def test_replacing_drops_the_old_pointer():
    # A new answer pointing somewhere must not leave the last pointer hanging
    # around, aimed at something no longer relevant.
    scene = Scene()
    scene.add(Pointer(0, 0))
    scene.replace([Highlight(5, 5, 10, 10)])

    assert scene.visible_items() == [Highlight(5, 5, 10, 10)]


# -- tutorials --------------------------------------------------------------


def steps(*texts):
    return [Step(text, Pointer(index, index)) for index, text in enumerate(texts)]


def test_a_tutorial_starts_on_its_first_step():
    scene = Scene()
    scene.start_tutorial(steps("Ouvrez le menu", "Cliquez sur Fichier"))

    assert scene.in_tutorial
    assert scene.current_step.text == "Ouvrez le menu"
    assert scene.progress() == "1 / 2"


def test_a_tutorial_replaces_loose_annotations():
    scene = Scene()
    scene.add(Pointer(99, 99))
    scene.start_tutorial(steps("un"))

    assert scene.visible_items() == [Pointer(0, 0)]


def test_next_and_previous():
    scene = Scene()
    scene.start_tutorial(steps("a", "b", "c"))

    assert scene.next_step() is True
    assert scene.current_step.text == "b"
    assert scene.previous_step() is True
    assert scene.current_step.text == "a"


def test_navigation_stops_at_both_ends():
    scene = Scene()
    scene.start_tutorial(steps("a", "b"))

    assert scene.previous_step() is False
    assert scene.current_step.text == "a"
    scene.next_step()
    assert scene.next_step() is False
    assert scene.is_last_step


def test_blank_steps_are_dropped():
    scene = Scene()
    scene.start_tutorial([Step("  "), Step("réel"), Step("")])

    assert len(scene.steps) == 1
    assert scene.current_step.text == "réel"


def test_a_step_without_a_target_draws_nothing_but_still_counts():
    scene = Scene()
    scene.start_tutorial([Step("Lisez ceci", None)])

    assert scene.in_tutorial
    assert scene.visible_items() == []


def test_tutorial_steps_do_not_expire():
    # A walkthrough goes at the user's pace, not the clock's.
    scene = Scene()
    scene.start_tutorial(steps("a", "b"))
    scene.tick(10_000)

    assert scene.in_tutorial
    assert scene.visible_items()


# -- clearing ---------------------------------------------------------------


def test_clear_removes_everything():
    scene = Scene()
    scene.add(Pointer(0, 0))
    scene.start_tutorial(steps("a"))
    scene.clear()

    assert scene.empty
    assert not scene.in_tutorial
    assert scene.progress() == ""
