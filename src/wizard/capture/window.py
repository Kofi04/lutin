"""Point at a window by dropping the avatar on it, then capture it.

Win32 reports window rectangles in *physical* pixels while Qt works in logical
ones, so `physical_to_logical` converts before anything is drawn or grabbed.
That conversion uses one screen's scale factor, which is exact on a single-DPI
desktop and approximate if two monitors run different scaling - the highlight
may sit a few pixels off in that case, never the wrong window.

The capture grabs the screen area the window occupies, so a window hidden
behind another would come out covered. That is fine for this interaction: you
drop the avatar on a window you can see.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QCursor,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QWidget

from .. import winapi
from .region import grab_rect

#: coucou's palette for the attach halo, reused as a rotating conical border.
_HALO_COLORS = ("#FF6B5B", "#F7B32B", "#2DD4A7", "#38BDF8", "#A78BFA", "#F472B6")
_HALO_WIDTH = 3.0
_HALO_PERIOD_S = 3.0
_HALO_FPS_MS = 50


def physical_to_logical(
    left: int, top: int, right: int, bottom: int, reference: QPoint | None = None
) -> QRect:
    """Convert a Win32 rect (physical px) to Qt coordinates (logical px)."""
    point = reference if reference is not None else QCursor.pos()
    screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
    ratio = (screen.devicePixelRatio() if screen else 1.0) or 1.0

    return QRect(
        round(left / ratio),
        round(top / ratio),
        round((right - left) / ratio),
        round((bottom - top) / ratio),
    )


def window_under_cursor(ignore: set[int] | None = None):
    """The top-level window under the mouse, or None.

    `ignore` must contain our own window handles - the avatar is always-on-top,
    so it is what sits under the cursor while you drag it.
    """
    point = QCursor.pos()
    screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
    ratio = (screen.devicePixelRatio() if screen else 1.0) or 1.0
    return winapi.window_at(round(point.x() * ratio), round(point.y() * ratio), ignore)


def capture_window(info) -> QImage | None:
    """Grab the screen area a window occupies."""
    rect = physical_to_logical(info.left, info.top, info.right, info.bottom)
    return grab_rect(rect)


class WindowHighlight(QWidget):
    """A click-through frame drawn around the window being pointed at."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)

        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(_HALO_FPS_MS)
        self._timer.timeout.connect(self._advance)

    def show_around(self, rect: QRect) -> None:
        """Frame `rect` (logical coordinates), growing slightly to sit outside it."""
        margin = math.ceil(_HALO_WIDTH)
        self.setGeometry(rect.adjusted(-margin, -margin, margin, margin))
        if not self.isVisible():
            self.show()
            self.raise_()
        if not self._timer.isActive():
            self._timer.start()

    def hide_halo(self) -> None:
        self._timer.stop()
        self.hide()

    def _advance(self) -> None:
        self._phase = (self._phase + _HALO_FPS_MS / 1000.0 / _HALO_PERIOD_S) % 1.0
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        centre = self.rect().center()
        gradient = QConicalGradient(centre, self._phase * 360.0)
        count = len(_HALO_COLORS)
        for index, colour in enumerate(_HALO_COLORS):
            gradient.setColorAt(index / count, QColor(colour))
        gradient.setColorAt(1.0, QColor(_HALO_COLORS[0]))  # close the loop

        pen = QPen(gradient, _HALO_WIDTH)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        inset = _HALO_WIDTH / 2
        painter.drawRoundedRect(
            self.rect().adjusted(inset, inset, -inset, -inset), 6, 6
        )
