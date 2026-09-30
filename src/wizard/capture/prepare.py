"""Turning a grabbed image into something worth sending to Claude.

The sizing rules live in `fit_within`, deliberately free of Qt, so the maths is
unit-testable without a display. Everything else is a thin wrapper over QImage.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QBuffer, QByteArray, Qt
from PySide6.QtGui import QImage

from ..overlay.mapping import CaptureFrame

#: Claude downsamples images whose long edge exceeds this, so sending anything
#: bigger costs upload time and tokens for detail that is thrown away anyway.
MAX_EDGE = 1568

#: Roughly how many pixels one image token covers. Used only to show the user
#: an order of magnitude before sending, never for billing.
_PIXELS_PER_TOKEN = 750


class CaptureKind(Enum):
    REGION = "region"
    WINDOW = "window"
    FILE = "file"
    SCREEN = "screen"


def fit_within(width: int, height: int, max_edge: int = MAX_EDGE) -> tuple[int, int]:
    """Scale (width, height) down so neither edge exceeds `max_edge`.

    Never scales *up*: a 200x100 thumbnail stays 200x100. Aspect ratio is
    preserved, and each edge is clamped to at least 1 so a very thin strip does
    not collapse to zero.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid image size: {width}x{height}")

    longest = max(width, height)
    if longest <= max_edge:
        return width, height

    ratio = max_edge / longest
    return max(1, round(width * ratio)), max(1, round(height * ratio))


def estimate_tokens(width: int, height: int) -> int:
    """Rough token cost of an image this size, for the pre-send preview."""
    return max(1, round(width * height / _PIXELS_PER_TOKEN))


@dataclass(frozen=True)
class Capture:
    """One thing the user chose to show Claude, ready to send."""

    kind: CaptureKind
    label: str  # shown in the context pill, e.g. "Chrome - Gmail"
    image: QImage  # already downscaled
    png: bytes  # encoded once, reused for the preview and the request
    #: Where on the desktop the image came from, so Claude's coordinates can
    #: be mapped back onto the screen. None for a dropped file, which has no
    #: place on the screen to point at.
    frame: CaptureFrame | None = None

    @property
    def width(self) -> int:
        return self.image.width()

    @property
    def height(self) -> int:
        return self.image.height()

    @property
    def estimated_tokens(self) -> int:
        return estimate_tokens(self.width, self.height)

    def base64_png(self) -> str:
        """The `data` field of an image content block."""
        return base64.standard_b64encode(self.png).decode("ascii")

    def summary(self) -> str:
        return (
            f"{self.label} · {self.width}×{self.height} · "
            f"~{self.estimated_tokens} tokens"
        )


def _encode_png(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.setData(QByteArray())
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("could not encode the capture as PNG")
    return bytes(buffer.data())


def prepare(
    image: QImage,
    kind: CaptureKind,
    label: str,
    max_edge: int = MAX_EDGE,
    region: tuple[float, float, float, float] | None = None,
) -> Capture:
    """Downscale, encode and wrap a grabbed image."""
    if image.isNull():
        raise ValueError("the capture is empty")

    target_w, target_h = fit_within(image.width(), image.height(), max_edge)
    if (target_w, target_h) != (image.width(), image.height()):
        image = image.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,  # fit_within already kept it
            Qt.TransformationMode.SmoothTransformation,
        )

    # Drop the alpha channel: screen grabs carry a useless one, and it inflates
    # the PNG for no visual gain.
    if image.hasAlphaChannel():
        image = image.convertToFormat(QImage.Format.Format_RGB888)

    # Recorded *after* downscaling, against the image actually sent: that is
    # the one size Claude's coordinates are expressed in.
    frame = None
    if region is not None:
        left, top, width, height = region
        frame = CaptureFrame(
            left, top, width, height, image.width(), image.height()
        )

    return Capture(
        kind=kind, label=label, image=image, png=_encode_png(image), frame=frame
    )
