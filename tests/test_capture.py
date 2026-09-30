"""Image sizing and encoding for captures sent to Claude."""

from __future__ import annotations

import base64

import pytest
from PySide6.QtGui import QColor, QImage

from wizard.capture import CaptureKind, estimate_tokens, fit_within, prepare
from wizard.capture.prepare import MAX_EDGE


def image(width: int, height: int, colour: str = "#3366cc") -> QImage:
    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(QColor(colour))
    return img


# -- fit_within -----------------------------------------------------------


def test_small_images_are_left_alone():
    assert fit_within(200, 100) == (200, 100)
    assert fit_within(MAX_EDGE, MAX_EDGE) == (MAX_EDGE, MAX_EDGE)


def test_landscape_is_capped_on_its_width():
    width, height = fit_within(3200, 1600)

    assert width == MAX_EDGE
    assert height == MAX_EDGE // 2


def test_portrait_is_capped_on_its_height():
    width, height = fit_within(1600, 3200)

    assert height == MAX_EDGE
    assert width == MAX_EDGE // 2


def test_aspect_ratio_survives_the_downscale():
    width, height = fit_within(2560, 1440)

    assert max(width, height) == MAX_EDGE
    assert abs(width / height - 2560 / 1440) < 0.01


def test_a_very_thin_strip_never_collapses_to_zero():
    width, height = fit_within(8000, 3)

    assert width == MAX_EDGE
    assert height == 1  # rounds to 0 without the clamp


def test_custom_max_edge():
    assert fit_within(1000, 500, max_edge=100) == (100, 50)


@pytest.mark.parametrize(("width", "height"), [(0, 100), (100, 0), (-5, 5)])
def test_invalid_sizes_raise(width, height):
    with pytest.raises(ValueError):
        fit_within(width, height)


# -- estimate_tokens ------------------------------------------------------


def test_token_estimate_grows_with_area():
    small = estimate_tokens(100, 100)
    big = estimate_tokens(1000, 1000)

    assert big > small
    assert estimate_tokens(1, 1) >= 1  # never zero, however tiny


# -- prepare --------------------------------------------------------------


def test_prepare_keeps_a_small_capture_untouched():
    capture = prepare(image(320, 200), CaptureKind.REGION, "Zone")

    assert (capture.width, capture.height) == (320, 200)
    assert capture.kind is CaptureKind.REGION
    assert capture.label == "Zone"


def test_prepare_downscales_an_oversized_capture():
    capture = prepare(image(4000, 2000), CaptureKind.SCREEN, "Écran")

    assert capture.width == MAX_EDGE
    assert capture.height == MAX_EDGE // 2


def test_prepare_produces_decodable_png():
    capture = prepare(image(64, 48), CaptureKind.WINDOW, "Chrome")

    assert capture.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert base64.standard_b64decode(capture.base64_png()) == capture.png

    # The PNG must round-trip to the same dimensions we advertised.
    decoded = QImage.fromData(capture.png, "PNG")
    assert (decoded.width(), decoded.height()) == (64, 48)


def test_prepare_drops_the_alpha_channel():
    transparent = QImage(32, 32, QImage.Format.Format_ARGB32)
    transparent.fill(QColor(0, 0, 0, 0))

    capture = prepare(transparent, CaptureKind.REGION, "Zone")

    assert not capture.image.hasAlphaChannel()


def test_summary_mentions_size_and_cost():
    summary = prepare(image(100, 50), CaptureKind.FILE, "capture.png").summary()

    assert "capture.png" in summary
    assert "100" in summary and "50" in summary
    assert "tokens" in summary


def test_prepare_rejects_an_empty_image():
    with pytest.raises(ValueError):
        prepare(QImage(), CaptureKind.REGION, "Zone")


# -- the frame, so Claude's coordinates can be mapped back ------------------


def test_a_screen_capture_records_where_it_came_from():
    from wizard.capture.prepare import prepare

    # 3136 logical pixels wide, from a monitor left of the primary.
    capture = prepare(
        image(3136, 1764, "#336699"),
        CaptureKind.REGION,
        "Zone",
        region=(-3136.0, 0.0, 3136.0, 1764.0),
    )

    assert capture.frame is not None
    assert (capture.frame.left, capture.frame.top) == (-3136.0, 0.0)
    # Recorded against the image as *sent*, after downscaling: that is the
    # only size Claude's coordinates can be in.
    assert (capture.frame.image_width, capture.frame.image_height) == (
        capture.width,
        capture.height,
    )
    assert capture.width == MAX_EDGE


def test_a_dropped_file_has_no_frame():
    from wizard.capture.prepare import prepare

    capture = prepare(image(200, 100, "#FFFFFF"), CaptureKind.FILE, "photo.png")

    # There is nowhere on the screen to point at.
    assert capture.frame is None


def test_a_capture_frame_maps_the_centre_back_to_the_region():
    from wizard.capture.prepare import prepare
    from wizard.overlay.mapping import image_to_logical

    capture = prepare(
        image(2000, 1000, "#000000"),
        CaptureKind.WINDOW,
        "Fenêtre",
        region=(100.0, 50.0, 2000.0, 1000.0),
    )
    centre = image_to_logical(capture.frame, capture.width / 2, capture.height / 2)

    assert (centre.x, centre.y) == (1100.0, 550.0)
