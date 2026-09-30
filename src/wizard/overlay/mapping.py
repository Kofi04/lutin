"""From "pixel (412, 230) of the image you sent me" to a point on the screen.

This is the part of on-screen guidance that has to be exactly right, because
every mistake here is a pointer confidently aimed at the wrong button.

Claude reasons in pixels of the image it received. That image is not the
screen: it was cropped to a region, grabbed at the monitor's device pixel ratio,
then downscaled so its long edge fits 1568 px. Getting back means undoing all
three, on a desktop where monitors can sit at negative coordinates and each can
have its own scale factor.

The trick that keeps it simple is to record, at capture time, the **logical**
rectangle the capture covered and the **final** size of the image sent. Device
pixels and the downscale then cancel out: the image spans the logical rectangle,
whatever happened in between, so a point is just a proportion of one mapped onto
the other. Recording anything else (the DPR, the downscale factor) would invite
reconstructing the same number two ways and having them disagree.

Pure: plain tuples in, plain tuples out, no Qt. Every rule is tested.
"""

from __future__ import annotations

from dataclasses import dataclass


class MappingError(ValueError):
    """The point or rectangle cannot be placed on the screen."""


@dataclass(frozen=True)
class CaptureFrame:
    """Where an image came from, in enough detail to map back onto the screen.

    Logical coordinates are Qt's: device-independent, spanning every monitor,
    and negative for a monitor placed left of or above the primary.
    """

    #: The logical rectangle on the desktop the image shows.
    left: float
    top: float
    width: float
    height: float
    #: The size, in pixels, of the image Claude actually received.
    image_width: int
    image_height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise MappingError(f"zone vide : {self.width}×{self.height}")
        if self.image_width <= 0 or self.image_height <= 0:
            raise MappingError(
                f"image vide : {self.image_width}×{self.image_height}"
            )

    @property
    def scale_x(self) -> float:
        """Logical pixels per image pixel, horizontally."""
        return self.width / self.image_width

    @property
    def scale_y(self) -> float:
        return self.height / self.image_height


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    #: True when the input fell outside the image and was pulled back onto it.
    clamped: bool = False


@dataclass(frozen=True)
class Rect:
    left: float
    top: float
    width: float
    height: float
    clamped: bool = False

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height

    @property
    def centre(self) -> tuple[float, float]:
        return (self.left + self.width / 2.0, self.top + self.height / 2.0)


def image_to_logical(frame: CaptureFrame, x: float, y: float) -> Point:
    """Map a point in the sent image to a logical point on the desktop.

    A point outside the image is clamped onto its edge rather than rejected:
    models occasionally report a coordinate a few pixels past the border, and
    pointing at the edge is far more useful than pointing nowhere. The result
    says it was clamped, so the caller can mention it.
    """
    if not _finite(x) or not _finite(y):
        raise MappingError(f"coordonnées invalides : ({x}, {y})")

    clamped_x = min(max(x, 0.0), float(frame.image_width))
    clamped_y = min(max(y, 0.0), float(frame.image_height))
    was_clamped = clamped_x != x or clamped_y != y

    return Point(
        x=frame.left + clamped_x * frame.scale_x,
        y=frame.top + clamped_y * frame.scale_y,
        clamped=was_clamped,
    )


def image_rect_to_logical(
    frame: CaptureFrame, x: float, y: float, width: float, height: float
) -> Rect:
    """Map a rectangle in the sent image to a logical rectangle on the desktop.

    Negative sizes are normalised (a model describing a box from its bottom
    right is still describing a box), and the result is clipped to the capture.
    """
    if width < 0:
        x, width = x + width, -width
    if height < 0:
        y, height = y + height, -height
    if width == 0 or height == 0:
        raise MappingError("un rectangle doit avoir une largeur et une hauteur")

    top_left = image_to_logical(frame, x, y)
    bottom_right = image_to_logical(frame, x + width, y + height)
    mapped_width = bottom_right.x - top_left.x
    mapped_height = bottom_right.y - top_left.y
    if mapped_width <= 0 or mapped_height <= 0:
        # Entirely outside the image: both corners clamped to the same edge.
        raise MappingError("le rectangle est entièrement hors de la capture")

    return Rect(
        left=top_left.x,
        top=top_left.y,
        width=mapped_width,
        height=mapped_height,
        clamped=top_left.clamped or bottom_right.clamped,
    )


def logical_to_image(frame: CaptureFrame, x: float, y: float) -> tuple[float, float]:
    """The inverse, for tests and for describing a screen point to Claude."""
    return (
        (x - frame.left) / frame.scale_x,
        (y - frame.top) / frame.scale_y,
    )


def normalised_to_logical(frame: CaptureFrame, nx: float, ny: float) -> Point:
    """Map a point given as a fraction of the image (0..1) instead of pixels.

    Offered because some prompts are easier to answer as "about two thirds of
    the way across" than in pixels, and a fraction is immune to any confusion
    about which image size the model had in mind.
    """
    return image_to_logical(frame, nx * frame.image_width, ny * frame.image_height)


def _finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))
