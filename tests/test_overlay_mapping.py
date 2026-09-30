"""Mapping Claude's image coordinates back onto the desktop.

Every failure here is a pointer confidently aimed at the wrong button, so the
cases are the ones real desktops produce: every common scale factor, monitors at
negative coordinates, captures large enough to be downscaled, and points a model
reports just past the edge of the image.
"""

from __future__ import annotations

import math

import pytest

from wizard.capture.prepare import MAX_EDGE, fit_within
from wizard.overlay.mapping import (
    CaptureFrame,
    MappingError,
    image_rect_to_logical,
    image_to_logical,
    logical_to_image,
    normalised_to_logical,
)

#: The scale factors Windows offers out of the box.
SCALES = [1.0, 1.25, 1.5, 1.75, 2.0]


def frame_for(left, top, width, height, dpr=1.0) -> CaptureFrame:
    """Build the frame the capture pipeline would produce for this rectangle.

    Goes through the real `fit_within`, so these tests break if the downscale
    rule changes and the mapping is not updated with it.
    """
    device_w, device_h = round(width * dpr), round(height * dpr)
    image_w, image_h = fit_within(device_w, device_h, MAX_EDGE)
    return CaptureFrame(left, top, width, height, image_w, image_h)


# -- the simple case -------------------------------------------------------


def test_an_unscaled_capture_maps_one_to_one():
    frame = CaptureFrame(100, 200, 800, 600, 800, 600)

    point = image_to_logical(frame, 50, 40)

    assert (point.x, point.y) == (150, 240)
    assert not point.clamped


def test_the_origin_of_the_image_is_the_corner_of_the_capture():
    frame = CaptureFrame(300, 150, 640, 480, 640, 480)

    point = image_to_logical(frame, 0, 0)

    assert (point.x, point.y) == (300, 150)


def test_the_far_corner_of_the_image_is_the_far_corner_of_the_capture():
    frame = CaptureFrame(300, 150, 640, 480, 320, 240)

    point = image_to_logical(frame, 320, 240)

    assert (point.x, point.y) == pytest.approx((940, 630))


# -- downscaling ------------------------------------------------------------


def test_a_downscaled_image_maps_back_to_full_size():
    # A 3136-wide capture is sent at 1568: every image pixel is two logical ones.
    frame = CaptureFrame(0, 0, 3136, 1764, 1568, 882)

    point = image_to_logical(frame, 784, 441)

    assert (point.x, point.y) == pytest.approx((1568, 882))


@pytest.mark.parametrize("dpr", SCALES)
def test_every_scale_factor_lands_on_the_same_logical_point(dpr):
    # The same logical region, grabbed at different DPIs, produces images of
    # different sizes. The centre of each image must still be the centre of
    # the region: device pixels must cancel out entirely.
    frame = frame_for(200, 100, 1200, 800, dpr)

    point = image_to_logical(frame, frame.image_width / 2, frame.image_height / 2)

    assert (point.x, point.y) == pytest.approx((800, 500), abs=0.5)


@pytest.mark.parametrize("dpr", SCALES)
def test_a_full_screen_capture_at_every_scale(dpr):
    # A 1920x1080 logical screen at 2x is 3840x2160 device pixels, which gets
    # downscaled to 1568 wide. The bottom-right corner must still be the
    # bottom-right corner.
    frame = frame_for(0, 0, 1920, 1080, dpr)

    point = image_to_logical(frame, frame.image_width, frame.image_height)

    assert (point.x, point.y) == pytest.approx((1920, 1080), abs=1.0)


@pytest.mark.parametrize("dpr", SCALES)
def test_a_button_is_hit_within_a_pixel_at_every_scale(dpr):
    # What actually matters: a button at logical (1500, 60) on a 1920x1080
    # screen. Find it in the image Claude would see, map it back, and land on
    # it to within a pixel — well inside any clickable target.
    frame = frame_for(0, 0, 1920, 1080, dpr)
    ix, iy = logical_to_image(frame, 1500, 60)

    point = image_to_logical(frame, round(ix), round(iy))

    assert abs(point.x - 1500) <= frame.scale_x
    assert abs(point.y - 60) <= frame.scale_y


# -- negative coordinates --------------------------------------------------


def test_a_monitor_to_the_left_of_the_primary():
    # A second screen placed left of the primary starts at a negative x.
    frame = CaptureFrame(-1920, 0, 1920, 1080, 1568, 882)

    point = image_to_logical(frame, 784, 441)

    assert (point.x, point.y) == pytest.approx((-960, 540))


def test_a_monitor_above_the_primary():
    frame = CaptureFrame(0, -1080, 1920, 1080, 1568, 882)

    point = image_to_logical(frame, 0, 0)

    assert (point.x, point.y) == pytest.approx((0, -1080))


def test_a_region_straddling_the_negative_origin():
    frame = CaptureFrame(-400, -300, 800, 600, 800, 600)

    point = image_to_logical(frame, 400, 300)

    # The middle of the region is the desktop origin.
    assert (point.x, point.y) == pytest.approx((0, 0))


@pytest.mark.parametrize("dpr", SCALES)
def test_negative_origin_at_every_scale(dpr):
    frame = frame_for(-2560, -200, 2560, 1440, dpr)

    point = image_to_logical(frame, 0, 0)

    assert (point.x, point.y) == pytest.approx((-2560, -200))


# -- points off the edge ---------------------------------------------------


def test_a_point_past_the_right_edge_is_clamped_and_says_so():
    frame = CaptureFrame(0, 0, 800, 600, 800, 600)

    point = image_to_logical(frame, 812, 300)

    # Models do report a few pixels past the border. The edge is far more
    # useful than an error, and the flag lets the caller mention it.
    assert point.x == 800
    assert point.clamped


def test_a_negative_point_is_clamped_to_the_origin():
    frame = CaptureFrame(50, 50, 800, 600, 800, 600)

    point = image_to_logical(frame, -20, -5)

    assert (point.x, point.y) == (50, 50)
    assert point.clamped


def test_a_point_on_the_edge_is_not_marked_clamped():
    frame = CaptureFrame(0, 0, 800, 600, 800, 600)

    assert not image_to_logical(frame, 800, 600).clamped


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_coordinates_are_rejected(bad):
    frame = CaptureFrame(0, 0, 800, 600, 800, 600)

    with pytest.raises(MappingError):
        image_to_logical(frame, bad, 10)


# -- rectangles ------------------------------------------------------------


def test_a_rectangle_maps_both_corners():
    frame = CaptureFrame(100, 100, 1600, 1200, 800, 600)

    rect = image_rect_to_logical(frame, 10, 20, 100, 50)

    assert (rect.left, rect.top) == pytest.approx((120, 140))
    assert (rect.width, rect.height) == pytest.approx((200, 100))


def test_a_rectangle_given_backwards_is_normalised():
    frame = CaptureFrame(0, 0, 800, 600, 800, 600)

    # A box described from its bottom-right corner is still that box.
    rect = image_rect_to_logical(frame, 110, 70, -100, -50)

    assert (rect.left, rect.top, rect.width, rect.height) == (10, 20, 100, 50)


def test_a_rectangle_hanging_off_the_edge_is_clipped():
    frame = CaptureFrame(0, 0, 800, 600, 800, 600)

    rect = image_rect_to_logical(frame, 750, 550, 200, 200)

    assert rect.right == 800
    assert rect.bottom == 600
    assert rect.clamped


def test_a_rectangle_entirely_off_the_image_is_an_error():
    frame = CaptureFrame(0, 0, 800, 600, 800, 600)

    with pytest.raises(MappingError):
        image_rect_to_logical(frame, 900, 700, 50, 50)


def test_a_zero_sized_rectangle_is_an_error():
    frame = CaptureFrame(0, 0, 800, 600, 800, 600)

    with pytest.raises(MappingError):
        image_rect_to_logical(frame, 10, 10, 0, 40)


def test_a_rectangle_centre():
    frame = CaptureFrame(0, 0, 800, 600, 800, 600)

    rect = image_rect_to_logical(frame, 100, 100, 200, 100)

    assert rect.centre == (200, 150)


# -- round trips and fractions ---------------------------------------------


@pytest.mark.parametrize("dpr", SCALES)
@pytest.mark.parametrize("origin", [(0, 0), (-1920, 0), (1920, -540)])
def test_logical_to_image_and_back_is_the_identity(dpr, origin):
    frame = frame_for(origin[0], origin[1], 1920, 1080, dpr)

    corners = [
        (origin[0] + 10, origin[1] + 10),
        (origin[0] + 1900, origin[1] + 1070),
    ]
    for lx, ly in corners:
        ix, iy = logical_to_image(frame, lx, ly)
        back = image_to_logical(frame, ix, iy)
        assert (back.x, back.y) == pytest.approx((lx, ly))


def test_normalised_coordinates():
    frame = CaptureFrame(-1000, 200, 1000, 800, 500, 400)

    point = normalised_to_logical(frame, 0.5, 0.25)

    assert (point.x, point.y) == pytest.approx((-500, 400))


# -- invalid frames --------------------------------------------------------


@pytest.mark.parametrize(
    "size",
    [
        (0, 600, 800, 600),
        (800, 0, 800, 600),
        (800, 600, 0, 600),
        (800, 600, 800, 0),
    ],
)
def test_an_empty_frame_is_refused(size):
    width, height, image_width, image_height = size

    with pytest.raises(MappingError):
        CaptureFrame(0, 0, width, height, image_width, image_height)
