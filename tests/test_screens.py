"""Desktop coordinates <-> (screen, position): the protocol's one conversion."""

from __future__ import annotations

import pytest

from wizard.screens import ScreenArea, from_screen, to_screen

# A laptop at 150 % (1280x720 logical) with a 1920x1080 monitor to its left,
# whose top sits 200 px higher: negative coordinates, as Windows produces them.
LAPTOP = ScreenArea(r"\\.\DISPLAY1", 0, 0, 1280, 720)
LEFT = ScreenArea(r"\\.\DISPLAY2", -1920, -200, 1920, 1080)
SCREENS = [LAPTOP, LEFT]


def test_point_on_the_primary_screen():
    assert to_screen(100, 50, SCREENS) == (LAPTOP.id, 100, 50)


def test_point_on_a_screen_with_negative_coordinates():
    assert to_screen(-1900, -150, SCREENS) == (LEFT.id, 20, 50)


def test_edges_belong_to_exactly_one_screen():
    assert to_screen(0, 0, SCREENS)[0] == LAPTOP.id
    assert to_screen(-1, 0, SCREENS)[0] == LEFT.id


def test_point_in_a_gap_goes_to_the_nearest_screen():
    # Below the laptop: LEFT goes down to 880, the laptop only to 720.
    screen_id, x, y = to_screen(100, 760, SCREENS)
    assert screen_id == LAPTOP.id
    assert (x, y) == (100, 760)  # kept as is: the UI clamps if it must


@pytest.mark.parametrize("point", [(5.5, 7.25), (-1919, 879), (1279, 719)])
def test_round_trip(point):
    screen_id, x, y = to_screen(*point, SCREENS)
    assert from_screen(screen_id, x, y, SCREENS) == point


def test_unknown_screen_is_an_error():
    with pytest.raises(ValueError):
        from_screen(r"\\.\DISPLAY9", 0, 0, SCREENS)


def test_no_screen_at_all_is_an_error():
    with pytest.raises(ValueError):
        to_screen(0, 0, [])
