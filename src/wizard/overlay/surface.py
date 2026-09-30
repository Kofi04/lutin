"""The transparent window that draws annotations on top of everything.

One per monitor, because a single window spanning a mixed-DPI desktop is
scaled by one monitor's factor and drawn blurry or misplaced on the others.
Each surface covers exactly its own screen and draws only what falls on it.

It must never take a click. Qt's WindowTransparentForInput plus
WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE (set explicitly, see
`winapi.make_click_through`) means the mouse and the keyboard go straight to
whatever is underneath. An overlay that eats one click breaks the very app it
is trying to explain.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

from .. import winapi
from ..design.tokens import Theme
from .scene import Highlight, Pointer

#: How far the rest of the screen dims behind a highlight. Enough to pull the
#: eye, not enough to hide what the user needs to see around it.
_DIM_ALPHA = 92
_PULSE_MS = 40
_ARROW_LENGTH = 96.0


class OverlaySurface(QWidget):
    """Draws the scene's items that fall on one screen."""

    def __init__(self, screen, theme: Theme):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())

        self._screen = screen
        self._theme = theme
        self._items: list[Pointer | Highlight] = []
        self._step_badge: tuple[int, int] | None = None
        self._phase = 0.0

        self._pulse = QTimer(self)
        self._pulse.setInterval(_PULSE_MS)
        self._pulse.timeout.connect(self._advance)

    # -- content -----------------------------------------------------------

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def set_items(
        self,
        items: list[Pointer | Highlight],
        step: tuple[int, int] | None = None,
    ) -> None:
        """Show the given items (logical desktop coordinates)."""
        geometry = QRectF(self._screen.geometry())
        self._items = [item for item in items if _touches(item, geometry)]
        self._step_badge = step
        if self._items:
            if not self.isVisible():
                self.show()
                self._harden()
            self._pulse.start()
        else:
            self._pulse.stop()
            self.hide()
        self.update()

    def _harden(self) -> None:
        """Apply the Win32 styles once the native window exists.

        No SetWindowDisplayAffinity here: this window is translucent, and
        Windows refuses it on translucent windows (error 8). Keeping it out
        of our own captures is the capture cloak's job instead.
        """
        winapi.make_click_through(int(self.winId()))

    def _advance(self) -> None:
        self._phase = (self._phase + _PULSE_MS / 1000.0) % 60.0
        self.update()

    # -- drawing -----------------------------------------------------------

    def paintEvent(self, event) -> None:
        if not self._items:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        origin = QPointF(self._screen.geometry().topLeft())

        highlights = [item for item in self._items if isinstance(item, Highlight)]
        if highlights:
            self._draw_dim(painter, highlights, origin)

        for item in self._items:
            if isinstance(item, Highlight):
                self._draw_highlight(painter, item, origin)
            else:
                self._draw_pointer(painter, item, origin)
        painter.end()

    def _accent(self) -> QColor:
        return QColor(self._theme.palette.accent)

    def _local(self, x: float, y: float, origin: QPointF) -> QPointF:
        return QPointF(x - origin.x(), y - origin.y())

    def _draw_dim(self, painter, highlights, origin) -> None:
        """Dim the screen, with a hole cut for each highlight."""
        veil = QPainterPath()
        veil.addRect(QRectF(self.rect()))
        for item in highlights:
            hole = QPainterPath()
            rect = QRectF(
                self._local(item.left, item.top, origin),
                self._local(item.left + item.width, item.top + item.height, origin),
            ).adjusted(-6, -6, 6, 6)
            if item.shape == "ellipse":
                hole.addEllipse(rect)
            else:
                hole.addRoundedRect(rect, 10, 10)
            veil = veil.subtracted(hole)
        painter.fillPath(veil, QColor(0, 0, 0, _DIM_ALPHA))

    def _draw_highlight(self, painter, item: Highlight, origin) -> None:
        rect = QRectF(
            self._local(item.left, item.top, origin),
            self._local(item.left + item.width, item.top + item.height, origin),
        ).adjusted(-6, -6, 6, 6)

        pulse = 0.5 + 0.5 * math.sin(self._phase * 4.0)
        accent = self._accent()

        glow = QColor(accent)
        glow.setAlpha(int(70 + 60 * pulse))
        painter.setPen(QPen(glow, 9.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        self._shape(painter, rect, item.shape)

        painter.setPen(QPen(accent, 2.6))
        self._shape(painter, rect, item.shape)

        if item.label:
            below = QPointF(rect.center().x(), rect.bottom() + 14)
            self._bubble(painter, item.label, below)
        if self._step_badge:
            self._badge(painter, self._step_badge[0], rect.topLeft())

    def _shape(self, painter, rect: QRectF, shape: str) -> None:
        if shape == "ellipse":
            painter.drawEllipse(rect)
        else:
            painter.drawRoundedRect(rect, 10, 10)

    def _draw_pointer(self, painter, item: Pointer, origin) -> None:
        tip = self._local(item.x, item.y, origin)
        # The arrow comes from whichever side has room, so it never points in
        # from off-screen at something near an edge.
        from_left = tip.x() > self.width() / 2
        from_top = tip.y() > self.height() / 2
        bob = 5.0 * math.sin(self._phase * 5.0)
        dx = -1.0 if from_left else 1.0
        dy = -1.0 if from_top else 1.0
        length = _ARROW_LENGTH
        tail = QPointF(
            tip.x() + dx * length * 0.72, tip.y() + dy * length * 0.72
        )
        head = QPointF(tip.x() + dx * (6 + bob), tip.y() + dy * (6 + bob))

        accent = self._accent()
        shaft = QPainterPath(tail)
        control = QPointF(
            tail.x() - dx * length * 0.05, head.y() + dy * length * 0.35
        )
        shaft.quadTo(control, head)

        halo = QColor(accent)
        halo.setAlpha(90)
        painter.setPen(QPen(halo, 11.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(shaft)
        painter.setPen(QPen(accent, 4.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(shaft)

        # Arrowhead, oriented along the last stretch of the curve.
        angle = math.atan2(head.y() - control.y(), head.x() - control.x())
        wing = 16.0
        spread = math.radians(28)
        left = QPointF(
            head.x() - wing * math.cos(angle - spread),
            head.y() - wing * math.sin(angle - spread),
        )
        right = QPointF(
            head.x() - wing * math.cos(angle + spread),
            head.y() - wing * math.sin(angle + spread),
        )
        arrow = QPainterPath(head)
        arrow.lineTo(left)
        arrow.lineTo(right)
        arrow.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawPath(arrow)

        # A ring on the target itself, so the exact spot is unmistakable.
        ring = QColor(accent)
        ring.setAlpha(int(140 + 80 * (0.5 + 0.5 * math.sin(self._phase * 5.0))))
        painter.setPen(QPen(ring, 2.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(tip, 9.0, 9.0)

        if item.label:
            self._bubble(painter, item.label, tail)
        if self._step_badge:
            self._badge(painter, self._step_badge[0], tail)

    def _bubble(self, painter, text: str, anchor: QPointF) -> None:
        """A label in a rounded card, kept fully on its screen."""
        palette = self._theme.palette
        font = QFont(painter.font())
        font.setPointSizeF(10.5)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        width = min(metrics.horizontalAdvance(text), 360.0)
        bounds = metrics.boundingRect(
            QRectF(0, 0, width, 400), int(Qt.TextFlag.TextWordWrap), text
        )
        box = QRectF(0, 0, bounds.width() + 24, bounds.height() + 16)
        box.moveCenter(anchor)
        box = _keep_inside(box, QRectF(self.rect()).adjusted(8, 8, -8, -8))

        painter.setPen(QPen(QColor(palette.border), 1.0))
        painter.setBrush(QColor(palette.surface_raised))
        painter.drawRoundedRect(box, 10, 10)
        painter.setPen(QColor(palette.text))
        painter.drawText(
            box.adjusted(12, 8, -12, -8),
            int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter),
            text,
        )

    def _badge(self, painter, number: int, anchor: QPointF) -> None:
        """A numbered circle, for tutorial steps."""
        palette = self._theme.palette
        centre = QPointF(anchor.x(), anchor.y())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.accent))
        painter.drawEllipse(centre, 15.0, 15.0)
        font = QFont(painter.font())
        font.setPointSizeF(11)
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(palette.on_accent))
        painter.drawText(
            QRectF(centre.x() - 15, centre.y() - 15, 30, 30),
            int(Qt.AlignmentFlag.AlignCenter),
            str(number),
        )


def _touches(item, screen: QRectF) -> bool:
    if isinstance(item, Pointer):
        return screen.contains(QPointF(item.x, item.y))
    return screen.intersects(QRectF(item.left, item.top, item.width, item.height))


def _keep_inside(box: QRectF, bounds: QRectF) -> QRectF:
    if box.left() < bounds.left():
        box.moveLeft(bounds.left())
    if box.right() > bounds.right():
        box.moveRight(bounds.right())
    if box.top() < bounds.top():
        box.moveTop(bounds.top())
    if box.bottom() > bounds.bottom():
        box.moveBottom(bounds.bottom())
    return box

