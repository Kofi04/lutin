"""The placeholder avatar, drawn entirely with QPainter.

Drawing the character in code rather than loading a sprite sheet means there
are no assets to ship yet and the whole thing stays crisp at any DPI. When you
bring real art, replace `draw_avatar` with a QSvgRenderer or a sprite-sheet
blitter: the window code below only ever calls this one function.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen

from .mood import Mood

# Base design size. Everything below is expressed as a fraction of this, so the
# avatar scales cleanly.
BASE_SIZE = 96

_PALETTE = {
    # From the machine.
    Mood.CALM: ("#5EDCCF", "#2FA89B"),
    Mood.BUSY: ("#FFD166", "#E9A400"),
    Mood.STRESSED: ("#FF8787", "#DC3A3A"),
    Mood.TIRED: ("#B3A4EA", "#6C4BC4"),
    # From Claude. WAITING is amber on purpose: it is the one state that needs
    # you to look, so it must not blend into the calm teal.
    Mood.WORKING: ("#7FC4FF", "#2F80D8"),
    Mood.WAITING: ("#FFC163", "#E08700"),
    Mood.DONE: ("#7BE8B3", "#2FA86B"),
    Mood.ERROR: ("#FF9B9B", "#C42B2B"),
}

_INK = QColor("#1B2430")


@dataclass
class SpriteState:
    """Everything the painter needs to know for one frame."""

    mood: Mood = Mood.CALM
    time: float = 0.0  # seconds since start, drives the idle animation
    eye_open: float = 1.0  # 0 = shut, 1 = wide
    # Cursor direction, each axis in [-1, 1]. QPointF is mutable, hence factory.
    look: QPointF = field(default_factory=QPointF)
    pressed: bool = False
    hovered: bool = False
    # The contact shadow sells the float on the desktop, but an app icon has
    # nothing to float above, so the icon renderer turns it off.
    shadow: bool = True
    # Enlarges the eyes and thickens the mouth. At 16px the face is only a
    # handful of pixels and the default proportions blur into the body, so the
    # icon renderer exaggerates them the way icon designers hint small sizes.
    feature_scale: float = 1.0
    # A file is hovering over the avatar: it squares up into a box, ready to
    # swallow whatever is dropped.
    catching: bool = False


def draw_avatar(painter: QPainter, size: float, state: SpriteState) -> None:
    """Draw the avatar into a `size` x `size` square at the painter's origin."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.save()
    painter.scale(size / BASE_SIZE, size / BASE_SIZE)

    # Idle bob, plus a squash when pressed so clicks feel physical.
    bob = math.sin(state.time * 2.0) * 1.8
    squash = 0.90 if state.pressed else 1.0 + math.sin(state.time * 2.0) * 0.015

    light, dark = _PALETTE[state.mood]

    if state.shadow:
        _draw_shadow(painter, bob)

    painter.save()
    painter.translate(BASE_SIZE / 2, BASE_SIZE / 2 + bob)
    painter.scale(1.0 / squash if squash else 1.0, squash)
    painter.translate(-BASE_SIZE / 2, -BASE_SIZE / 2)

    body = QRectF(12, 14, BASE_SIZE - 24, BASE_SIZE - 32)
    _draw_body(painter, body, light, dark, state.hovered, state.catching)
    _draw_face(painter, body, state)
    if not state.catching:
        _draw_mood_accent(painter, body, state)

    painter.restore()
    painter.restore()


def _draw_shadow(painter: QPainter, bob: float) -> None:
    # The shadow shrinks as the body rises, which is what sells the float.
    spread = 1.0 - bob / 12.0
    width = 42 * spread
    rect = QRectF(BASE_SIZE / 2 - width / 2, BASE_SIZE - 14, width, 8)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, int(46 * spread)))
    painter.drawEllipse(rect)


def _draw_body(
    painter: QPainter,
    body: QRectF,
    light: str,
    dark: str,
    hovered: bool,
    catching: bool = False,
) -> None:
    gradient = QLinearGradient(body.topLeft(), body.bottomRight())
    gradient.setColorAt(0.0, QColor(light))
    gradient.setColorAt(1.0, QColor(dark))

    path = QPainterPath()
    # A generous corner radius on a near-square gives a blob, not a rectangle.
    # Squaring it off is what reads as "box, ready to catch something".
    radius = 0.12 if catching else 0.46
    path.addRoundedRect(body, body.width() * radius, body.height() * radius * 0.96)

    painter.setBrush(QBrush(gradient))
    painter.setPen(QPen(QColor(dark).darker(125), 2.0) if hovered else Qt.PenStyle.NoPen)
    painter.drawPath(path)

    # Specular highlight, top-left.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 58))
    painter.drawEllipse(
        QRectF(
            body.left() + body.width() * 0.16,
            body.top() + body.height() * 0.12,
            body.width() * 0.34,
            body.height() * 0.24,
        )
    )


def _draw_face(painter: QPainter, body: QRectF, state: SpriteState) -> None:
    eye_y = body.top() + body.height() * 0.42
    eye_dx = body.width() * 0.20
    centre_x = body.center().x()

    eye_w = body.width() * 0.155 * state.feature_scale
    eye_h = eye_w * 1.25 * max(0.08, state.eye_open)

    for sign in (-1, 1):
        cx = centre_x + sign * eye_dx
        sclera = QRectF(cx - eye_w / 2, eye_y - eye_h / 2, eye_w, eye_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 240))
        painter.drawEllipse(sclera)

        if state.eye_open > 0.35:
            # Pupils drift toward the cursor, but stay inside the sclera.
            pupil_r = eye_w * 0.30
            max_shift = eye_w * 0.22
            pupil = QRectF(0, 0, pupil_r * 2, pupil_r * 2)
            pupil.moveCenter(
                QPointF(
                    cx + state.look.x() * max_shift,
                    eye_y + state.look.y() * max_shift * 0.8,
                )
            )
            painter.setBrush(_INK)
            painter.drawEllipse(pupil)

    _draw_mouth(painter, body, state)


def _draw_mouth(painter: QPainter, body: QRectF, state: SpriteState) -> None:
    mouth_y = body.top() + body.height() * 0.68
    width = body.width() * 0.28
    left = body.center().x() - width / 2

    pen = QPen(_INK, 2.4 * state.feature_scale)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    path = QPainterPath()
    if state.mood in (Mood.CALM, Mood.DONE):
        # Gentle smile. DONE grins a little wider.
        curve = width * (0.72 if state.mood is Mood.DONE else 0.55)
        path.moveTo(left, mouth_y)
        path.quadTo(body.center().x(), mouth_y + curve, left + width, mouth_y)
    elif state.mood in (Mood.BUSY, Mood.WORKING):
        # Focused straight line.
        path.moveTo(left, mouth_y + 2)
        path.lineTo(left + width, mouth_y + 2)
    elif state.mood is Mood.WAITING:
        # A small "o": it is about to ask you something.
        painter.setBrush(_INK)
        painter.drawEllipse(
            QRectF(
                body.center().x() - width * 0.16,
                mouth_y - 1,
                width * 0.32,
                width * 0.32,
            )
        )
        return
    elif state.mood in (Mood.STRESSED, Mood.ERROR):
        # Open, worried mouth.
        painter.setBrush(_INK)
        painter.drawEllipse(
            QRectF(left + width * 0.2, mouth_y - 1, width * 0.6, width * 0.52)
        )
        return
    else:  # TIRED - a small wavy line
        step = width / 4
        path.moveTo(left, mouth_y)
        for index in range(4):
            path.quadTo(
                left + step * (index + 0.5),
                mouth_y + (4 if index % 2 == 0 else -4),
                left + step * (index + 1),
                mouth_y,
            )
    painter.drawPath(path)


def _draw_mood_accent(painter: QPainter, body: QRectF, state: SpriteState) -> None:
    """A small badge that makes the mood readable at a glance."""
    if state.mood is Mood.WAITING:
        # A pulsing "!" - the one badge that is asking you for something, so it
        # must be the loudest thing the avatar ever does.
        pulse = 0.72 + 0.28 * abs(math.sin(state.time * 3.4))
        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(13 * pulse)
        painter.setFont(font)
        painter.setPen(QColor("#1B2430"))
        painter.setBrush(QColor("#FFFFFF"))
        badge = QRectF(body.right() - 15, body.top() - 5, 17, 17)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(badge)
        painter.setPen(QColor("#B26A00"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "!")
        return

    if state.mood is Mood.ERROR:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#C42B2B"))
        painter.drawEllipse(QRectF(body.right() - 13, body.top() - 3, 12, 12))
        return

    if state.mood is Mood.DONE:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2FA86B"))
        painter.drawEllipse(QRectF(body.right() - 13, body.top() - 3, 12, 12))
        return

    if state.mood is Mood.STRESSED:
        # Sweat drop on the upper right.
        drop = QPainterPath()
        top = QPointF(body.right() - 2, body.top() + 6)
        drop.moveTo(top)
        drop.cubicTo(
            QPointF(top.x() + 6, top.y() + 7),
            QPointF(top.x() + 4, top.y() + 14),
            QPointF(top.x(), top.y() + 14),
        )
        drop.cubicTo(
            QPointF(top.x() - 4, top.y() + 14),
            QPointF(top.x() - 6, top.y() + 7),
            top,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#63C7FF"))
        painter.drawPath(drop)

    elif state.mood is Mood.TIRED:
        # Floating "z"s that rise and fade. The travel is kept small so the
        # glyphs stay inside the widget rect and never get clipped away.
        font = painter.font()
        font.setBold(True)
        for index in range(2):
            phase = (state.time * 0.6 + index * 0.5) % 1.0
            font.setPointSizeF(8 + index * 3)
            painter.setFont(font)
            colour = QColor(255, 255, 255)
            colour.setAlphaF(max(0.0, 1.0 - phase))
            painter.setPen(colour)
            painter.drawText(
                QPointF(
                    body.right() - 14 + index * 4,
                    body.top() + 13 - phase * 8 - index * 3,
                ),
                "z",
            )

    elif state.mood in (Mood.BUSY, Mood.WORKING):
        # A spinner arc, because "busy" reads best as motion.
        rect = QRectF(body.right() - 16, body.top() - 4, 14, 14)
        pen = QPen(QColor(255, 255, 255, 230), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        start = int(-state.time * 260 * 16) % (360 * 16)
        painter.drawArc(rect, start, 250 * 16)
