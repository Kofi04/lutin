"""The sprite-sheet loader: the path hand-drawn art takes into the app."""

from __future__ import annotations

import json

import pytest
from PySide6.QtGui import QColor, QImage, QPainter

from wizard.character.animation import Frame, still_frame
from wizard.character.emote import Emote
from wizard.character.painter import PainterRenderer
from wizard.character.renderer import load_renderer
from wizard.character.sheet import Clip, SheetRenderer


def write_frame(directory, name: str, colour: str = "#FF0000", side: int = 32):
    directory.mkdir(parents=True, exist_ok=True)
    image = QImage(side, side, QImage.Format.Format_ARGB32)
    image.fill(QColor(colour))
    assert image.save(str(directory / name), "PNG")
    return directory / name


def draw_to_image(renderer, frame: Frame, side: int = 32) -> QImage:
    image = QImage(side, side, QImage.Format.Format_ARGB32)
    image.fill(QColor("#000000"))
    painter = QPainter(image)
    renderer.draw(painter, float(side), frame)
    painter.end()
    return image


# -- loading ---------------------------------------------------------------


def test_an_empty_folder_is_declined(tmp_path):
    assert SheetRenderer.load(tmp_path) is None


def test_a_missing_folder_is_declined(tmp_path):
    assert SheetRenderer.load(tmp_path / "nope") is None


def test_a_folder_without_idle_is_declined(tmp_path):
    # Every other pose falls back to idle, so a set without it has no floor.
    write_frame(tmp_path, "wizard_speaking_1.png")

    assert SheetRenderer.load(tmp_path) is None


def test_idle_alone_is_enough(tmp_path):
    write_frame(tmp_path, "wizard_idle_1.png")
    renderer = SheetRenderer.load(tmp_path)

    assert renderer is not None
    assert renderer.name == "sheet"
    assert renderer.has(Emote.IDLE)


def test_missing_poses_are_reported_not_fatal(tmp_path):
    write_frame(tmp_path, "wizard_idle_1.png")
    write_frame(tmp_path, "wizard_success_1.png")
    renderer = SheetRenderer.load(tmp_path)

    assert Emote.SPEAKING in renderer.missing
    assert Emote.IDLE not in renderer.missing
    # And drawing an absent pose still draws something.
    draw_to_image(renderer, still_frame(Emote.SPEAKING))


def test_unrelated_files_are_ignored(tmp_path):
    write_frame(tmp_path, "wizard_idle_1.png")
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "wizard_notapose_1.png").write_bytes(b"not a png")

    assert SheetRenderer.load(tmp_path) is not None


def test_unreadable_images_do_not_crash_the_load(tmp_path):
    write_frame(tmp_path, "wizard_idle_1.png")
    (tmp_path / "wizard_busy_1.png").write_bytes(b"truncated garbage")
    renderer = SheetRenderer.load(tmp_path)

    assert renderer is not None
    assert Emote.BUSY in renderer.missing


def test_frames_are_ordered_numerically_not_alphabetically(tmp_path):
    # "wizard_idle_10.png" sorts before "wizard_idle_2.png" as text, which would
    # play the animation out of order.
    for index, colour in ((1, "#FF0000"), (2, "#00FF00"), (10, "#0000FF")):
        write_frame(tmp_path, f"wizard_idle_{index}.png", colour)
    renderer = SheetRenderer.load(tmp_path)

    clip = renderer._clips[Emote.IDLE]
    assert len(clip.frames) == 3

    first = clip.at(0.0).toImage().pixelColor(1, 1)
    third = clip.at(2.0 / clip.fps).toImage().pixelColor(1, 1)
    assert first == QColor("#FF0000")
    assert third == QColor("#0000FF")


def test_zero_padded_names_load(tmp_path):
    write_frame(tmp_path, "wizard_idle_001.png")

    assert SheetRenderer.load(tmp_path) is not None


# -- the manifest ----------------------------------------------------------


def test_the_manifest_can_set_the_frame_rate(tmp_path):
    write_frame(tmp_path, "wizard_idle_1.png")
    (tmp_path / "wizard.json").write_text(json.dumps({"fps": 24}), encoding="utf-8")
    renderer = SheetRenderer.load(tmp_path)

    assert renderer._clips[Emote.IDLE].fps == pytest.approx(24.0)


def test_a_broken_manifest_is_ignored_not_fatal(tmp_path):
    write_frame(tmp_path, "wizard_idle_1.png")
    (tmp_path / "wizard.json").write_text("{ not json", encoding="utf-8")

    assert SheetRenderer.load(tmp_path) is not None


def test_one_shots_default_to_not_looping(tmp_path):
    write_frame(tmp_path, "wizard_idle_1.png")
    write_frame(tmp_path, "wizard_greeting_1.png")
    write_frame(tmp_path, "wizard_greeting_2.png")
    renderer = SheetRenderer.load(tmp_path)

    assert renderer._clips[Emote.GREETING].loop is False
    assert renderer._clips[Emote.IDLE].loop is True


# -- playback --------------------------------------------------------------


def test_a_looping_clip_wraps_around():
    clip = Clip(frames=["a", "b", "c"], fps=10.0, loop=True)

    assert clip.at(0.0) == "a"
    assert clip.at(0.1) == "b"
    assert clip.at(0.3) == "a"


def test_a_non_looping_clip_holds_its_last_frame():
    clip = Clip(frames=["a", "b"], fps=10.0, loop=False)

    assert clip.at(0.1) == "b"
    assert clip.at(99.0) == "b"


def test_a_single_frame_clip_never_indexes_out_of_range():
    clip = Clip(frames=["only"], fps=12.0, loop=True)

    assert clip.at(0.0) == "only"
    assert clip.at(1000.0) == "only"


def test_a_negative_time_does_not_index_backwards():
    clip = Clip(frames=["a", "b", "c"], fps=10.0, loop=False)

    assert clip.at(-5.0) == "a"


# -- choosing a renderer ---------------------------------------------------


def test_load_renderer_falls_back_to_code(tmp_path):
    renderer = load_renderer(tmp_path)

    assert renderer.name == "painter"


def test_load_renderer_prefers_art_when_it_exists(tmp_path):
    write_frame(tmp_path, "wizard_idle_1.png")
    renderer = load_renderer(tmp_path)

    assert renderer.name == "sheet"


def test_both_renderers_satisfy_the_same_call(tmp_path):
    write_frame(tmp_path, "wizard_idle_1.png")
    frame = still_frame(Emote.WORKING)

    for renderer in (PainterRenderer(), SheetRenderer.load(tmp_path)):
        image = draw_to_image(renderer, frame)
        assert image.width() == 32


def test_a_transition_draws_both_poses(tmp_path):
    write_frame(tmp_path, "wizard_idle_1.png", "#FF0000")
    write_frame(tmp_path, "wizard_busy_1.png", "#0000FF")
    renderer = SheetRenderer.load(tmp_path)

    mid = Frame(emote=Emote.BUSY, previous=Emote.IDLE, blend=0.5)
    image = draw_to_image(renderer, mid)

    # Half red over half blue: neither channel may be at zero, which is what a
    # transition that silently drew only one side would give.
    colour = image.pixelColor(16, 16)
    assert colour.red() > 20
    assert colour.blue() > 20
