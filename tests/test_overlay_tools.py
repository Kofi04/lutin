"""The tools Claude calls to draw on the screen.

What matters as much as drawing is refusing: a tool that draws an arrow at a
guessed spot because it had no screen capture to map against is worse than one
that says it cannot.
"""

from __future__ import annotations

import asyncio

import pytest

from wizard.overlay.mapping import CaptureFrame
from wizard.overlay.scene import Highlight, Pointer
from wizard.overlay.tools import (
    QUALIFIED,
    SERVER,
    TOOL_NAMES,
    OverlayBridge,
    build_handlers,
)

#: A 2x downscaled capture of a monitor left of the primary.
FRAME = CaptureFrame(-1920, 0, 1920, 1080, 960, 540)


class Recorder:
    def __init__(self, bridge: OverlayBridge) -> None:
        self.points: list[tuple] = []
        self.highlights: list[tuple] = []
        self.steps: list = []
        self.clears = 0
        bridge.point_requested.connect(lambda *a: self.points.append(a))
        bridge.highlight_requested.connect(lambda *a: self.highlights.append(a))
        bridge.steps_requested.connect(self.steps.append)
        bridge.clear_requested.connect(self._clear)

    def _clear(self) -> None:
        self.clears += 1


@pytest.fixture
def setup():
    bridge = OverlayBridge()
    recorder = Recorder(bridge)
    frame_box = {"frame": FRAME}
    handlers = build_handlers(bridge, lambda: frame_box["frame"])
    return handlers, recorder, frame_box


def call(handler, **args):
    return asyncio.run(handler(args))


def text_of(result) -> str:
    return result["content"][0]["text"]


# -- point_at --------------------------------------------------------------


def test_point_at_maps_to_the_desktop(setup):
    handlers, recorder, _ = setup

    result = call(handlers["point_at"], x=480, y=270, label="Ici")

    assert not result["is_error"]
    # The middle of a 2x-downscaled capture of the left monitor.
    assert recorder.points == [(-960.0, 540.0, "Ici")]


def test_point_at_without_a_label(setup):
    handlers, recorder, _ = setup

    call(handlers["point_at"], x=0, y=0)

    assert recorder.points == [(-1920.0, 0.0, "")]


def test_point_at_past_the_edge_is_clamped_and_says_so(setup):
    handlers, recorder, _ = setup

    result = call(handlers["point_at"], x=2000, y=100)

    assert recorder.points[0][0] == 0.0  # the right edge of the left monitor
    assert "bord" in text_of(result)


def test_point_at_refuses_without_a_screen_capture(setup):
    handlers, recorder, frame_box = setup
    frame_box["frame"] = None  # e.g. the user dropped a photo instead

    result = call(handlers["point_at"], x=10, y=10)

    assert result["is_error"]
    assert recorder.points == []


def test_point_at_rejects_nonsense(setup):
    handlers, recorder, _ = setup

    result = call(handlers["point_at"], x="nan", y=10)

    assert result["is_error"]
    assert recorder.points == []


# -- highlight -------------------------------------------------------------


def test_highlight_maps_the_rectangle(setup):
    handlers, recorder, _ = setup

    call(handlers["highlight"], x=100, y=50, width=200, height=100, label="Bouton")

    left, top, width, height, label, shape = recorder.highlights[0]
    assert (left, top, width, height) == (-1720.0, 100.0, 400.0, 200.0)
    assert (label, shape) == ("Bouton", "rect")


def test_highlight_accepts_an_ellipse(setup):
    handlers, recorder, _ = setup

    call(handlers["highlight"], x=0, y=0, width=10, height=10, shape="ellipse")

    assert recorder.highlights[0][5] == "ellipse"


def test_highlight_falls_back_from_an_unknown_shape(setup):
    handlers, recorder, _ = setup

    call(handlers["highlight"], x=0, y=0, width=10, height=10, shape="star")

    assert recorder.highlights[0][5] == "rect"


def test_highlight_entirely_off_the_capture_is_refused(setup):
    handlers, recorder, _ = setup

    result = call(handlers["highlight"], x=5000, y=5000, width=10, height=10)

    assert result["is_error"]
    assert recorder.highlights == []


# -- show_steps ------------------------------------------------------------


def test_show_steps_builds_a_tutorial(setup):
    handlers, recorder, _ = setup

    result = call(
        handlers["show_steps"],
        steps=[
            {"text": "Ouvrez le menu", "x": 10, "y": 10},
            {"text": "Choisissez Exporter", "x": 20, "y": 30, "width": 40, "height": 10},
            {"text": "Validez"},
        ],
    )

    assert not result["is_error"]
    steps = recorder.steps[0]
    assert [step.text for step in steps] == [
        "Ouvrez le menu",
        "Choisissez Exporter",
        "Validez",
    ]
    assert isinstance(steps[0].target, Pointer)
    assert isinstance(steps[1].target, Highlight)
    assert steps[2].target is None


def test_show_steps_drops_blank_steps_and_reports_them(setup):
    handlers, recorder, _ = setup

    result = call(handlers["show_steps"], steps=[{"text": "  "}, {"text": "Réel"}])

    assert [step.text for step in recorder.steps[0]] == ["Réel"]
    assert "ignorée" in text_of(result)


def test_show_steps_with_nothing_usable_is_an_error(setup):
    handlers, recorder, _ = setup

    result = call(handlers["show_steps"], steps=[{"text": ""}])

    assert result["is_error"]
    assert recorder.steps == []


def test_a_bad_position_keeps_the_step_and_drops_the_position(setup):
    handlers, recorder, _ = setup

    result = call(
        handlers["show_steps"],
        steps=[{"text": "Là-bas", "x": 9000, "y": 9000, "width": 5, "height": 5}],
    )

    # The instruction is still worth showing even if its location is wrong.
    assert recorder.steps[0][0].text == "Là-bas"
    assert recorder.steps[0][0].target is None
    assert "position ignorée" in text_of(result)


# -- clear -----------------------------------------------------------------


def test_clear_works_without_a_capture(setup):
    handlers, recorder, frame_box = setup
    frame_box["frame"] = None

    result = call(handlers["clear_overlay"])

    # Clearing never needs coordinates, so it never needs a capture.
    assert not result["is_error"]
    assert recorder.clears == 1


# -- naming ---------------------------------------------------------------


def test_qualified_names_follow_the_mcp_convention():
    assert tuple(f"mcp__{SERVER}__{name}" for name in TOOL_NAMES) == QUALIFIED
    assert "mcp__wizard__point_at" in QUALIFIED
