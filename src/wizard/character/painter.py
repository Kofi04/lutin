"""Little Wizard, drawn with QPainter.

A small African wizard: dark skin, big round eyes, a round compact silhouette
(large head, small body), an indigo robe and a pointed hat banded with sober
geometric bogolan- and kente-inspired motifs, cowrie shells, and a carved staff
whose tip lights up according to what the app is doing.

Three things shape every decision in here:

* **It has to read at 48px, and survive 16px.** So the silhouette carries the
  character — hat, head, two big eyes — and detail is layered on top rather
  than load-bearing. `Frame.feature_scale` exaggerates the face for icon sizes.
* **Poses share a body.** Only the face, the arms, the accent and the props
  change. That is what makes a transition cheap: the shared base is drawn once
  and only the pose-specific parts cross-fade, which avoids the muddy
  double-exposure you get from fading two whole characters into each other.
* **Nothing here knows about time.** `animation.py` owns the clock; this file
  is a pure function of one `Frame`.

Coordinates are in design units against `BASE_SIZE` (96), origin top-left.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)

from .animation import Frame
from .emote import Emote
from .palette import (
    CREAM,
    GOLD,
    INDIGO,
    INDIGO_DEEP,
    INDIGO_LIT,
    INK,
    OCRE,
    SKIN,
    SKIN_LIT,
    SKIN_SHADOW,
    TERRACOTTA,
    accent,
)
from .renderer import BASE_SIZE

# Anatomy, in design units. Named so the geometry below reads as a face rather
# than a pile of magic numbers.
#
# Proportions are the whole game for a mascot. The head is deliberately huge
# (a third of the height, wider than the shoulders) and the eyes are huge
# within it, because that is what reads as "cute" rather than "small man". The
# brim sits high, on top of the skull rather than across the face: the first
# draft had it at the eyeline and the head read as a brown box.
_HEAD = QPointF(48.0, 48.0)
_HEAD_R = 17.0
_BRIM_Y = 31.0
_BRIM_W = 44.0
_BRIM_H = 9.5
_HAT_TIP = QPointF(54.0, 4.0)
_ROBE_TOP = 64.0
_ROBE_BOTTOM = 86.0
_SHADOW_Y = 88.0
_STAFF_TOP = QPointF(77.0, 30.0)
_STAFF_FOOT = QPointF(71.0, 87.0)

_INK = QColor(INK)


#: Poses whose body moves frame to frame, so caching it would freeze the
#: animation. Both are transient, so redrawing them in full costs nothing that
#: lasts.
_UNCACHEABLE = frozenset({Emote.GREETING, Emote.POINTING})

#: Plenty for the handful of sizes in play (the avatar, the tray, nine icon
#: sizes) while bounding the memory a long-running process holds.
_CACHE_LIMIT = 48

#: Complete figures: blink steps x light-pulse steps for the current pose,
#: plus a few for hovering. Small pixmaps; evicted oldest first.
_FIGURE_CACHE_LIMIT = 96


#: Poses with a prop or a mouth that moves every frame: never skipped.
_ALWAYS_MOVING = frozenset(
    {
        Emote.THINKING,
        Emote.WAITING_APPROVAL,
        Emote.SLEEPING,
        Emote.TIRED,
        Emote.SUCCESS,
        Emote.CONFUSED,
        Emote.GREETING,
        Emote.LISTENING,
        Emote.SPEAKING,
    }
)


class PainterRenderer:
    """Draws the wizard from code. No assets required.

    The body — robe, woven bands, head, hat, sleeves — is gradients, clipped
    paths and dozens of small shapes, and none of it changes between frames. At
    the avatar's idle frame rate, redrawing it every time cost 5% of a core,
    which is a lot to pay for a character that is standing still. So it is
    rendered once into a pixmap and blitted, and only what actually moves —
    eyes, mouth, the staff's light, the props — is drawn live on top.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple, QPixmap] = {}
        self._figures: dict[tuple, QPixmap] = {}

    @property
    def name(self) -> str:
        return "painter"

    def visual_key(self, frame: Frame, size: float):
        """What this frame looks like, coarsely, or None if it must be drawn.

        At idle the bob moves the whole character by under two pixels, so
        most consecutive frames are identical once rounded to the screen —
        and drawing them anyway was most of the app's idle CPU (measured:
        about 2 ms of QPainter work per frame, 10 frames a second). Equal
        keys mean the frame can be skipped. Poses with something moving
        continuously (orbiting stars, rising z's, a talking mouth) return
        None and are always drawn.
        """
        if frame.emote in _ALWAYS_MOVING:
            return None
        if frame.previous is not None and frame.blend < 1.0:
            return None
        scale = size / BASE_SIZE
        bob, squash = _bounce(frame)
        return (
            frame.emote,
            round(bob * scale * 2),  # half-pixel steps on screen
            round((squash - 1.0) * size * 2),  # its effect on height, in half pixels
            round(frame.eye_open, 1),
            round(frame.look[0], 1),
            round(frame.look[1], 1),
            round(_orb_pulse(frame) * 8),
            frame.connection,
            frame.pressed,
            frame.hovered,
            frame.catching,
            frame.feature_scale,
            frame.aim,
        )

    def draw(self, painter: QPainter, size: float, frame: Frame) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.save()
        painter.scale(size / BASE_SIZE, size / BASE_SIZE)

        bob, squash = _bounce(frame)

        if frame.shadow:
            _draw_shadow(painter, bob)

        painter.save()
        # Squash about the feet, not the centre: a character that shrinks toward
        # its own middle looks like it is being crushed, not landing.
        painter.translate(BASE_SIZE / 2, _ROBE_BOTTOM + bob)
        painter.scale(1.0 / squash if squash else 1.0, squash)
        painter.translate(-BASE_SIZE / 2, -_ROBE_BOTTOM)

        figure = self._figure(painter, size, frame)
        if figure is not None:
            # The whole standing character, face and light included, drawn
            # once per look; the breathing is just where it is blitted.
            painter.drawPixmap(
                QRectF(0.0, 0.0, float(BASE_SIZE), float(BASE_SIZE)),
                figure,
                QRectF(0.0, 0.0, float(figure.width()), float(figure.height())),
            )
        else:
            self._paint_figure(painter, size, frame)

        painter.restore()
        painter.restore()

    def _paint_figure(self, painter: QPainter, size: float, frame: Frame) -> None:
        """Everything above the shadow, in design units, at the origin."""
        glow, halo = _accent_colours(frame)

        body = self._body(painter, size, frame, glow, halo)
        if body is None:
            _draw_body_layer(painter, frame, glow, halo)
        else:
            painter.drawPixmap(
                QRectF(0.0, 0.0, float(BASE_SIZE), float(BASE_SIZE)),
                body,
                QRectF(0.0, 0.0, float(body.width()), float(body.height())),
            )

        _draw_face(painter, frame)
        _draw_orb(painter, frame, _staff_pose(frame)[0], glow, halo)
        _draw_props(painter, frame, glow, halo)

    def _figure(self, painter: QPainter, size: float, frame: Frame) -> QPixmap | None:
        """The complete character for this look, cached; None if it moves too much.

        The cached body alone left the eyes, mouth and light to be redrawn on
        every frame, which was still most of the idle cost. Between blinks and
        light pulses nothing about the figure changes except where it sits, so
        the figure is keyed on what it looks like (`visual_key`, minus the bob)
        and only the position is applied per frame.
        """
        key = self.visual_key(frame, size)
        if key is None:
            return None
        ratio = getattr(painter.device(), "devicePixelRatioF", lambda: 1.0)() or 1.0
        pixels = max(1, int(round(size * ratio)))
        # Drop the bob and squash: those are applied when blitting.
        figure_key = (key[0], *key[3:], pixels)
        cached = self._figures.get(figure_key)
        if cached is not None:
            return cached

        pixmap = QPixmap(pixels, pixels)
        pixmap.fill(Qt.GlobalColor.transparent)
        into = QPainter(pixmap)
        into.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        into.scale(pixels / BASE_SIZE, pixels / BASE_SIZE)
        self._paint_figure(into, size, frame)
        into.end()

        if len(self._figures) >= _FIGURE_CACHE_LIMIT:
            # Oldest first: dicts keep insertion order.
            self._figures.pop(next(iter(self._figures)))
        self._figures[figure_key] = pixmap
        return pixmap

    # -- the cached body --------------------------------------------------

    def _body(
        self, painter: QPainter, size: float, frame: Frame, glow: QColor, halo: QColor
    ) -> QPixmap | None:
        """The still half of the character, rendered once per look."""
        if frame.emote in _UNCACHEABLE:
            return None

        device = painter.device()
        ratio = getattr(device, "devicePixelRatioF", lambda: 1.0)() or 1.0
        pixels = max(1, int(round(size * ratio)))
        # The transition blends two bodies; caching that would need a key per
        # blend step, so those few frames are drawn live.
        if frame.previous is not None and frame.blend < 1.0:
            return None

        key = (
            frame.emote,
            pixels,
            round(frame.feature_scale, 2),
            frame.catching,
            frame.hovered,
        )
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        pixmap = QPixmap(pixels, pixels)
        pixmap.fill(Qt.GlobalColor.transparent)
        into = QPainter(pixmap)
        into.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        into.scale(pixels / BASE_SIZE, pixels / BASE_SIZE)
        _draw_body_layer(into, frame, glow, halo)
        into.end()

        if len(self._cache) >= _CACHE_LIMIT:
            self._cache.clear()
        self._cache[key] = pixmap
        return pixmap


def _draw_body_layer(
    painter: QPainter, frame: Frame, glow: QColor, halo: QColor
) -> None:
    """Everything that does not move: the parts worth caching."""
    _draw_staff(painter, frame, glow, halo, orb=False)
    _draw_robe(painter, frame)
    _draw_arms(painter, frame)
    _draw_head(painter, frame)
    _draw_hat(painter, frame, glow)


# ---------------------------------------------------------------------------
# Motion that belongs to the drawing rather than to the animator: the bob and
# the squash are functions of the frame, not state of their own.
# ---------------------------------------------------------------------------


def _fine_detail(frame: Frame) -> bool:
    """False when we are drawing small enough that detail turns to mush.

    The icon renderer raises `feature_scale` at small sizes to keep the face
    readable; the same signal tells us to drop the cowries, the carved rings
    and the woven bands, which at 16px are noise that muddies the silhouette.
    """
    return frame.feature_scale < 1.15


def _bounce(frame: Frame) -> tuple[float, float]:
    if frame.emote is Emote.SLEEPING:
        # Slow, deep breathing; no float.
        return math.sin(frame.total_time * 0.9) * 0.8, 1.0
    speed = 3.2 if frame.emote in (Emote.WORKING, Emote.BUSY, Emote.THINKING) else 2.0
    bob = math.sin(frame.total_time * speed) * 1.7
    if frame.pressed:
        return bob, 0.90
    return bob, 1.0 + math.sin(frame.total_time * speed) * 0.014


def _accent_colours(frame: Frame) -> tuple[QColor, QColor]:
    """The staff's glow, blended across a transition so it never jumps."""
    core, halo = accent(frame.emote)
    current = (QColor(core), QColor(halo))
    if frame.previous is None or frame.blend >= 1.0:
        return current
    old_core, old_halo = accent(frame.previous)
    return (
        _mix(QColor(old_core), current[0], frame.blend),
        _mix(QColor(old_halo), current[1], frame.blend),
    )


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def _draw_shadow(painter: QPainter, bob: float) -> None:
    # The shadow tightens as he rises, which is what sells the float.
    spread = 1.0 - bob / 13.0
    width = 40.0 * spread
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, int(52 * spread)))
    painter.drawEllipse(
        QRectF(BASE_SIZE / 2 - width / 2, _SHADOW_Y, width, 7.0 * spread)
    )


# ---------------------------------------------------------------------------
# The robe
# ---------------------------------------------------------------------------


def _robe_path(frame: Frame) -> QPainterPath:
    """A bell: narrow at the shoulders, flared and rounded at the hem."""
    top_half = 11.5
    hem_half = 20.5 if not frame.catching else 22.5
    centre = BASE_SIZE / 2

    path = QPainterPath()
    path.moveTo(centre - top_half, _ROBE_TOP)
    path.cubicTo(
        QPointF(centre - top_half - 3.0, _ROBE_TOP + 12.0),
        QPointF(centre - hem_half, _ROBE_BOTTOM - 9.0),
        QPointF(centre - hem_half, _ROBE_BOTTOM - 3.0),
    )
    # A gently curved hem, so he reads as standing on cloth, not on a plank.
    path.quadTo(
        QPointF(centre, _ROBE_BOTTOM + 3.2),
        QPointF(centre + hem_half, _ROBE_BOTTOM - 3.0),
    )
    path.cubicTo(
        QPointF(centre + hem_half, _ROBE_BOTTOM - 9.0),
        QPointF(centre + top_half + 3.0, _ROBE_TOP + 12.0),
        QPointF(centre + top_half, _ROBE_TOP),
    )
    path.closeSubpath()
    return path


def _draw_robe(painter: QPainter, frame: Frame) -> None:
    path = _robe_path(frame)

    gradient = QLinearGradient(QPointF(30.0, _ROBE_TOP), QPointF(66.0, _ROBE_BOTTOM))
    gradient.setColorAt(0.0, QColor(INDIGO_LIT))
    gradient.setColorAt(0.55, QColor(INDIGO))
    gradient.setColorAt(1.0, QColor(INDIGO_DEEP))

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(gradient))
    painter.drawPath(path)

    # The hem band, clipped to the robe so the pattern follows the silhouette
    # instead of spilling past it.
    painter.save()
    painter.setClipPath(path)
    band = QRectF(24.0, _ROBE_BOTTOM - 12.0, 48.0, 7.2)
    painter.setBrush(QColor(TERRACOTTA))
    painter.drawRect(band)
    if _fine_detail(frame):
        _draw_kente_band(painter, band)

    # A single ocre stripe higher up, to break the expanse of indigo.
    painter.setBrush(QColor(OCRE))
    painter.drawRect(QRectF(24.0, _ROBE_BOTTOM - 15.0, 48.0, 1.5))
    painter.restore()

    if frame.hovered:
        painter.setPen(QPen(QColor(GOLD), 1.1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


def _draw_kente_band(painter: QPainter, band: QRectF) -> None:
    """Alternating triangles and small squares: sober, geometric, and legible."""
    painter.setPen(Qt.PenStyle.NoPen)
    step = 5.0
    x = band.left()
    index = 0
    while x < band.right():
        if index % 2 == 0:
            triangle = QPainterPath()
            triangle.moveTo(x, band.bottom())
            triangle.lineTo(x + step / 2.0, band.top() + 0.6)
            triangle.lineTo(x + step, band.bottom())
            triangle.closeSubpath()
            painter.setBrush(QColor(GOLD))
            painter.drawPath(triangle)
        else:
            painter.setBrush(QColor(INDIGO_DEEP))
            painter.drawRect(
                QRectF(x + step * 0.28, band.center().y() - 1.1, step * 0.44, 2.2)
            )
        x += step
        index += 1


# ---------------------------------------------------------------------------
# Arms: the one part of the body that changes with the pose
# ---------------------------------------------------------------------------


def _draw_arms(painter: QPainter, frame: Frame) -> None:
    painter.setPen(Qt.PenStyle.NoPen)

    # Left sleeve. Raised for a wave, cupped to the ear for listening, held out
    # flat when a scroll is being offered.
    if frame.emote is Emote.GREETING:
        wave = math.sin(frame.time * 9.0) * 0.30
        _sleeve(painter, QPointF(33.0, 63.0), QPointF(23.0, 47.0 + wave * 6.0))
        _hand(painter, QPointF(22.0, 44.0 + wave * 6.0), 3.6)
    elif frame.emote is Emote.LISTENING:
        _sleeve(painter, QPointF(33.0, 63.0), QPointF(29.0, 48.0))
        _hand(painter, QPointF(30.5, 45.0), 3.4)
    elif frame.emote is Emote.WAITING_APPROVAL:
        _sleeve(painter, QPointF(33.0, 63.0), QPointF(26.0, 62.0))
    elif frame.catching:
        _sleeve(painter, QPointF(33.0, 63.0), QPointF(28.0, 55.0))
        _hand(painter, QPointF(27.0, 53.0), 3.2)
    else:
        _sleeve(painter, QPointF(33.0, 62.0), QPointF(29.5, 71.0))

    # Right sleeve always reaches for the staff.
    _sleeve(painter, QPointF(62.0, 62.0), QPointF(69.0, 62.0))


def _sleeve(painter: QPainter, shoulder: QPointF, cuff: QPointF) -> None:
    pen = QPen(QColor(INDIGO), 7.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    path = QPainterPath(shoulder)
    # Bow the sleeve outward so it reads as cloth over an arm, not a stick.
    mid = QPointF(
        (shoulder.x() + cuff.x()) / 2.0 + (cuff.x() - shoulder.x()) * 0.25,
        (shoulder.y() + cuff.y()) / 2.0 + 2.0,
    )
    path.quadTo(mid, cuff)
    painter.drawPath(path)
    painter.setPen(Qt.PenStyle.NoPen)


def _hand(painter: QPainter, centre: QPointF, radius: float) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(SKIN))
    painter.drawEllipse(centre, radius, radius)


# ---------------------------------------------------------------------------
# Head and hat
# ---------------------------------------------------------------------------


def _draw_head(painter: QPainter, frame: Frame) -> None:
    painter.setPen(Qt.PenStyle.NoPen)

    gradient = QRadialGradient(
        QPointF(_HEAD.x() - 5.0, _HEAD.y() - 6.0), _HEAD_R * 1.9
    )
    gradient.setColorAt(0.0, QColor(SKIN_LIT))
    gradient.setColorAt(0.65, QColor(SKIN))
    gradient.setColorAt(1.0, QColor(SKIN_SHADOW))
    painter.setBrush(QBrush(gradient))
    painter.drawEllipse(_HEAD, _HEAD_R, _HEAD_R * 0.97)

    # Ears, just enough to break the circle.
    painter.setBrush(QColor(SKIN_SHADOW))
    for sign in (-1.0, 1.0):
        painter.drawEllipse(
            QPointF(_HEAD.x() + sign * (_HEAD_R - 0.6), _HEAD.y() + 2.0), 2.3, 3.0
        )

    if _fine_detail(frame):
        _draw_necklace(painter)


def _draw_necklace(painter: QPainter) -> None:
    """A cowrie strand at the collar."""
    painter.setPen(Qt.PenStyle.NoPen)
    for index in range(-2, 3):
        x = _HEAD.x() + index * 4.6
        y = _ROBE_TOP + 2.6 + abs(index) * 0.7
        _cowrie(painter, QPointF(x, y), 1.8)


def _cowrie(painter: QPainter, centre: QPointF, radius: float) -> None:
    """One cowrie shell: a cream oval with a dark slit. A cheap, honest motif."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(CREAM))
    painter.drawEllipse(centre, radius, radius * 0.78)
    pen = QPen(QColor(120, 96, 70), max(0.5, radius * 0.28))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(
        QPointF(centre.x() - radius * 0.45, centre.y()),
        QPointF(centre.x() + radius * 0.45, centre.y()),
    )
    painter.setPen(Qt.PenStyle.NoPen)


def _draw_hat(painter: QPainter, frame: Frame, glow: QColor) -> None:
    painter.setPen(Qt.PenStyle.NoPen)

    droop = 2.5 if frame.emote is Emote.SLEEPING else 0.0
    tip = QPointF(_HAT_TIP.x(), _HAT_TIP.y() + droop)

    # The cone, drawn as a curved wizard's hat rather than a straight triangle:
    # the bend is most of what makes it read as friendly.
    cone = QPainterPath()
    cone.moveTo(BASE_SIZE / 2 - _BRIM_W / 2 + 4.0, _BRIM_Y)
    cone.quadTo(QPointF(BASE_SIZE / 2 - 3.0, _BRIM_Y - 16.0), tip)
    cone.quadTo(
        QPointF(BASE_SIZE / 2 + 12.0, _BRIM_Y - 14.0),
        QPointF(BASE_SIZE / 2 + _BRIM_W / 2 - 4.0, _BRIM_Y),
    )
    cone.closeSubpath()

    gradient = QLinearGradient(QPointF(28.0, _BRIM_Y), QPointF(68.0, tip.y()))
    gradient.setColorAt(0.0, QColor(INDIGO))
    gradient.setColorAt(1.0, QColor(INDIGO_DEEP))
    painter.setBrush(QBrush(gradient))
    painter.drawPath(cone)

    # Hat band, clipped to the cone for the same reason as the robe's hem.
    painter.save()
    painter.setClipPath(cone)
    band = QRectF(BASE_SIZE / 2 - _BRIM_W / 2, _BRIM_Y - 7.0, _BRIM_W, 5.4)
    painter.setBrush(QColor(OCRE))
    painter.drawRect(band)
    if _fine_detail(frame):
        _draw_bogolan_band(painter, band)
    painter.restore()

    # Brim last, so it sits in front of the cone and the head.
    brim = QRectF(
        BASE_SIZE / 2 - _BRIM_W / 2, _BRIM_Y - _BRIM_H / 2, _BRIM_W, _BRIM_H
    )
    painter.setBrush(QColor(INDIGO_DEEP))
    painter.drawEllipse(brim)
    painter.setBrush(QColor(INDIGO))
    painter.drawEllipse(brim.adjusted(0.0, 0.0, 0.0, -2.2))

    # Two cowries pinned to the brim, and a star at the very tip.
    if _fine_detail(frame):
        _cowrie(painter, QPointF(BASE_SIZE / 2 - 13.0, _BRIM_Y - 1.0), 2.4)
        _cowrie(painter, QPointF(BASE_SIZE / 2 + 15.0, _BRIM_Y - 0.4), 2.1)
    _star(painter, QPointF(tip.x(), tip.y() + 1.0), 2.9, glow)


def _draw_bogolan_band(painter: QPainter, band: QRectF) -> None:
    """A row of diamonds with dots between them: mud-cloth geometry, simplified."""
    painter.setPen(Qt.PenStyle.NoPen)
    step = 7.0
    x = band.left() + 1.0
    while x < band.right():
        diamond = QPainterPath()
        cy = band.center().y()
        diamond.moveTo(x, cy)
        diamond.lineTo(x + step * 0.25, band.top() + 0.5)
        diamond.lineTo(x + step * 0.5, cy)
        diamond.lineTo(x + step * 0.25, band.bottom() - 0.5)
        diamond.closeSubpath()
        painter.setBrush(QColor(INDIGO_DEEP))
        painter.drawPath(diamond)
        painter.setBrush(QColor(CREAM))
        painter.drawEllipse(QPointF(x + step * 0.75, cy), 0.9, 0.9)
        x += step


def _star(painter: QPainter, centre: QPointF, radius: float, colour: QColor) -> None:
    """A four-pointed sparkle. Cheaper to read at small sizes than five points."""
    path = QPainterPath()
    for index in range(4):
        angle = math.pi / 2.0 * index
        tip = QPointF(
            centre.x() + math.cos(angle) * radius,
            centre.y() + math.sin(angle) * radius,
        )
        waist = QPointF(
            centre.x() + math.cos(angle + math.pi / 4.0) * radius * 0.34,
            centre.y() + math.sin(angle + math.pi / 4.0) * radius * 0.34,
        )
        if index == 0:
            path.moveTo(tip)
        else:
            path.lineTo(tip)
        path.lineTo(waist)
    path.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    painter.drawPath(path)


# ---------------------------------------------------------------------------
# The face: the only part that cross-fades between poses
# ---------------------------------------------------------------------------


def _draw_face(painter: QPainter, frame: Frame) -> None:
    _draw_eyes(painter, frame)

    if frame.previous is not None and frame.blend < 1.0:
        painter.save()
        painter.setOpacity(1.0 - frame.blend)
        _draw_expression(painter, frame, frame.previous)
        painter.restore()
        painter.save()
        painter.setOpacity(frame.blend)
        _draw_expression(painter, frame, frame.emote)
        painter.restore()
    else:
        _draw_expression(painter, frame, frame.emote)


def _draw_eyes(painter: QPainter, frame: Frame) -> None:
    scale = frame.feature_scale
    # Big. Each eye is nearly a quarter of the head's width: that, more than any
    # other single number in this file, is what makes him read as a character
    # instead of a figure.
    eye_w = 7.8 * scale
    shut = frame.emote is Emote.SLEEPING
    open_amount = 0.06 if shut else max(0.06, frame.eye_open)
    if frame.emote is Emote.SUCCESS:
        # Happy squint.
        open_amount *= 0.62
    eye_h = eye_w * 1.08 * open_amount
    eye_y = _HEAD.y() + 1.0
    dx = 7.0

    for sign in (-1.0, 1.0):
        cx = _HEAD.x() + sign * dx
        socket = QRectF(cx - eye_w / 2.0, eye_y - eye_h / 2.0, eye_w, eye_h)

        if open_amount < 0.18:
            pen = QPen(_INK, 1.5 * scale)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(
                QPointF(socket.left(), eye_y), QPointF(socket.right(), eye_y)
            )
            painter.setPen(Qt.PenStyle.NoPen)
            continue

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(CREAM))
        painter.drawEllipse(socket)

        pupil_r = eye_w * 0.31
        shift = eye_w * 0.20
        centre = QPointF(
            cx + frame.look[0] * shift, eye_y + frame.look[1] * shift * 0.75
        )
        painter.setBrush(_INK)
        painter.drawEllipse(centre, pupil_r, pupil_r)
        # A catchlight is what turns two dots into eyes.
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawEllipse(
            QPointF(centre.x() - pupil_r * 0.34, centre.y() - pupil_r * 0.40),
            pupil_r * 0.34,
            pupil_r * 0.34,
        )

    _draw_brows(painter, frame, eye_y, eye_w, dx)


def _draw_brows(
    painter: QPainter, frame: Frame, eye_y: float, eye_w: float, dx: float
) -> None:
    emote = frame.emote
    if emote in (Emote.IDLE, Emote.SUCCESS, Emote.GREETING, Emote.SLEEPING):
        return

    pen = QPen(_INK, 1.4 * frame.feature_scale)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)

    # Inner end down = concern; inner end up = surprise.
    if emote in (Emote.STRESSED, Emote.CONFUSED):
        inner, outer = -1.2, -3.4
    elif emote in (Emote.WORKING, Emote.BUSY, Emote.THINKING):
        inner, outer = -3.0, -2.2
    elif emote in (Emote.WAITING_APPROVAL, Emote.LISTENING, Emote.POINTING):
        inner, outer = -4.4, -3.6
    else:
        inner, outer = -3.4, -3.2

    top = eye_y - eye_w * 0.72
    for sign in (-1.0, 1.0):
        cx = _HEAD.x() + sign * dx
        painter.drawLine(
            QPointF(cx - sign * eye_w * 0.45, top + outer),
            QPointF(cx + sign * eye_w * 0.45, top + inner),
        )
    painter.setPen(Qt.PenStyle.NoPen)


def _draw_expression(painter: QPainter, frame: Frame, emote: Emote) -> None:
    """The mouth for one pose. Split out so a transition can fade two of them."""
    scale = frame.feature_scale
    y = _HEAD.y() + 9.6
    width = 9.0
    left = _HEAD.x() - width / 2.0

    pen = QPen(_INK, 2.0 * scale)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    path = QPainterPath()

    if emote in (Emote.IDLE, Emote.GREETING):
        path.moveTo(left, y)
        path.quadTo(QPointF(_HEAD.x(), y + width * 0.52), QPointF(left + width, y))
    elif emote is Emote.SUCCESS:
        # A proper grin, filled, because "it worked" deserves teeth.
        grin = QPainterPath()
        grin.moveTo(left - 0.6, y - 0.8)
        grin.quadTo(
            QPointF(_HEAD.x(), y + width * 0.88), QPointF(left + width + 0.6, y - 0.8)
        )
        grin.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_INK)
        painter.drawPath(grin)
        painter.setBrush(QColor(CREAM))
        top = QPainterPath()
        top.moveTo(left - 0.2, y - 0.4)
        top.quadTo(QPointF(_HEAD.x(), y + 1.6), QPointF(left + width + 0.2, y - 0.4))
        top.closeSubpath()
        painter.drawPath(top)
        _draw_cheeks(painter, y)
        return
    elif emote in (Emote.BUSY, Emote.WORKING):
        path.moveTo(left + 0.8, y + 0.6)
        path.lineTo(left + width - 0.8, y + 0.6)
    elif emote is Emote.THINKING:
        # Mouth pulled to one side: thinking, not talking.
        path.moveTo(left + 1.6, y + 0.8)
        path.quadTo(QPointF(_HEAD.x() + 1.6, y + 1.8), QPointF(left + width, y - 0.4))
    elif emote is Emote.WAITING_APPROVAL:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_INK)
        painter.drawEllipse(QPointF(_HEAD.x(), y + 1.0), width * 0.20, width * 0.24)
        return
    elif emote in (Emote.STRESSED, Emote.CONFUSED):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_INK)
        painter.drawEllipse(
            QRectF(left + width * 0.22, y - 0.8, width * 0.56, width * 0.50)
        )
        return
    elif emote is Emote.SPEAKING:
        # Opens and closes: the mouth is the animation here.
        openness = 0.25 + 0.75 * abs(math.sin(frame.time * 11.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_INK)
        painter.drawEllipse(
            QRectF(
                left + width * 0.26,
                y - width * 0.10,
                width * 0.48,
                width * 0.16 + width * 0.40 * openness,
            )
        )
        return
    elif emote is Emote.LISTENING:
        path.moveTo(left + 1.4, y + 0.4)
        path.quadTo(QPointF(_HEAD.x(), y + 2.4), QPointF(left + width - 1.4, y + 0.4))
    elif emote is Emote.POINTING:
        path.moveTo(left + 1.0, y)
        path.quadTo(QPointF(_HEAD.x(), y + width * 0.42), QPointF(left + width - 1.0, y))
    elif emote is Emote.SLEEPING:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_INK)
        painter.drawEllipse(QPointF(_HEAD.x() + 0.5, y + 0.6), width * 0.15, width * 0.19)
        return
    else:  # TIRED - a small wavy line
        step = width / 4.0
        path.moveTo(left, y)
        for index in range(4):
            wave = 2.0 if index % 2 == 0 else -2.0
            path.quadTo(
                QPointF(left + step * (index + 0.5), y + wave),
                QPointF(left + step * (index + 1), y),
            )

    painter.drawPath(path)
    painter.setPen(Qt.PenStyle.NoPen)


def _draw_cheeks(painter: QPainter, mouth_y: float) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(196, 92, 70, 90))
    for sign in (-1.0, 1.0):
        painter.drawEllipse(QPointF(_HEAD.x() + sign * 11.0, mouth_y - 2.0), 2.8, 1.9)


# ---------------------------------------------------------------------------
# The staff, which carries the state light
# ---------------------------------------------------------------------------


def _draw_staff(
    painter: QPainter, frame: Frame, glow: QColor, halo: QColor, orb: bool = True
) -> None:
    top, foot = _staff_pose(frame)

    pen = QPen(QColor(120, 78, 44), 2.9)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(top, foot)

    # Two carved rings, so it is a carved staff and not a dowel.
    if not _fine_detail(frame):
        painter.setPen(Qt.PenStyle.NoPen)
        if orb:
            _draw_orb(painter, frame, top, glow, halo)
        return
    ring = QPen(QColor(GOLD), 1.5)
    painter.setPen(ring)
    for t in (0.33, 0.52):
        painter.drawLine(
            QPointF(top.x() + (foot.x() - top.x()) * t - 1.8,
                    top.y() + (foot.y() - top.y()) * t),
            QPointF(top.x() + (foot.x() - top.x()) * t + 1.8,
                    top.y() + (foot.y() - top.y()) * t),
        )
    painter.setPen(Qt.PenStyle.NoPen)

    if orb:
        _draw_orb(painter, frame, top, glow, halo)


def _staff_pose(frame: Frame) -> tuple[QPointF, QPointF]:
    """Where the staff is. Pointing swings it; sleeping lowers it."""
    if frame.emote is Emote.POINTING:
        # Swing the tip toward the aim direction, kept within a sane arc so it
        # never crosses his own face.
        ax, ay = frame.aim
        return (
            QPointF(74.0 + ax * 9.0, 24.0 + ay * 12.0),
            QPointF(69.0, 80.0),
        )
    if frame.emote is Emote.SLEEPING:
        return QPointF(80.0, 38.0), QPointF(70.0, 86.0)
    if frame.emote is Emote.GREETING:
        return QPointF(78.0, 24.0), _STAFF_FOOT
    return _STAFF_TOP, _STAFF_FOOT


#: The soft halo, pre-rendered once per colour. Building a QRadialGradient and
#: filling a 28-unit circle with it on every frame was the single most expensive
#: thing left after the body was cached, and it is the same picture every time:
#: only its size and opacity change, and the painter can do both for free.
_GLOW_PX = 64
_glow_cache: dict[int, QPixmap] = {}


def _glow_pixmap(halo: QColor) -> QPixmap:
    key = halo.rgb()
    cached = _glow_cache.get(key)
    if cached is not None:
        return cached

    pixmap = QPixmap(_GLOW_PX, _GLOW_PX)
    pixmap.fill(Qt.GlobalColor.transparent)
    into = QPainter(pixmap)
    into.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    centre = QPointF(_GLOW_PX / 2.0, _GLOW_PX / 2.0)
    gradient = QRadialGradient(centre, _GLOW_PX / 2.0)
    core = QColor(halo)
    core.setAlpha(150)
    gradient.setColorAt(0.0, core)
    edge = QColor(halo)
    edge.setAlpha(0)
    gradient.setColorAt(1.0, edge)
    into.setPen(Qt.PenStyle.NoPen)
    into.setBrush(QBrush(gradient))
    into.drawEllipse(centre, _GLOW_PX / 2.0, _GLOW_PX / 2.0)
    into.end()

    if len(_glow_cache) > 32:
        _glow_cache.clear()
    _glow_cache[key] = pixmap
    return pixmap


def _draw_orb(
    painter: QPainter, frame: Frame, top: QPointF, glow: QColor, halo: QColor
) -> None:
    if frame.connection != "ready":
        # The light is the link to Claude as well as the mood. Draining its
        # colour is a quieter way to say "not connected" than a second badge,
        # and it cannot be confused with a mood: no mood is grey.
        glow, halo = _connection_colours(frame)

    pulse = _orb_pulse(frame)
    radius = 3.3 + 0.7 * pulse

    reach = radius * 4.2
    painter.save()
    painter.setOpacity(painter.opacity() * (0.45 + 0.55 * pulse))
    painter.drawPixmap(
        QRectF(top.x() - reach, top.y() - reach, reach * 2.0, reach * 2.0),
        _glow_pixmap(halo),
        QRectF(0.0, 0.0, float(_GLOW_PX), float(_GLOW_PX)),
    )
    painter.restore()

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(halo)
    painter.drawEllipse(top, radius, radius)
    painter.setBrush(glow)
    painter.drawEllipse(top, radius * 0.62, radius * 0.62)
    painter.setBrush(QColor(255, 255, 255, 210))
    painter.drawEllipse(
        QPointF(top.x() - radius * 0.26, top.y() - radius * 0.30),
        radius * 0.26,
        radius * 0.26,
    )


def _connection_colours(frame: Frame) -> tuple[QColor, QColor]:
    """A draining light while connecting, a dead grey one when offline."""
    if frame.connection == "connecting":
        return QColor("#C9C2AE"), QColor("#8C8674")
    return QColor("#7E8496"), QColor("#565C6E")


def _orb_pulse(frame: Frame) -> float:
    """0..1. What the light is doing tells you what the app is doing."""
    if frame.connection == "connecting":
        # A slow breath, so "trying" is visibly different from "given up".
        return 0.2 + 0.8 * abs(math.sin(frame.total_time * 2.2))
    if frame.connection == "offline":
        return 0.0
    if frame.emote is Emote.LISTENING:
        # Follows your voice, so you can see that the microphone is live.
        return 0.25 + 0.75 * frame.level
    if frame.emote is Emote.WAITING_APPROVAL:
        return abs(math.sin(frame.total_time * 3.4))
    if frame.emote in (Emote.WORKING, Emote.THINKING, Emote.BUSY):
        return 0.5 + 0.5 * abs(math.sin(frame.total_time * 2.6))
    if frame.emote is Emote.SLEEPING:
        return 0.12
    if frame.emote is Emote.SPEAKING:
        return 0.4 + 0.6 * abs(math.sin(frame.time * 8.0))
    return 0.45 + 0.25 * math.sin(frame.total_time * 1.4)


# ---------------------------------------------------------------------------
# Props and per-pose extras
# ---------------------------------------------------------------------------


def _draw_props(
    painter: QPainter, frame: Frame, glow: QColor, halo: QColor
) -> None:
    emote = frame.emote

    if emote is Emote.THINKING:
        _draw_orbiting_symbols(painter, frame, glow)
    elif emote is Emote.WAITING_APPROVAL:
        _draw_scroll(painter, frame)
    elif emote is Emote.SLEEPING or emote is Emote.TIRED:
        _draw_zzz(painter, frame)
    elif emote is Emote.STRESSED:
        _draw_sweat(painter)
    elif emote is Emote.SUCCESS:
        _draw_sparkles(painter, frame, glow)
    elif emote is Emote.LISTENING:
        _draw_sound_waves(painter, frame, halo)
    elif emote is Emote.CONFUSED:
        _draw_question(painter, frame, halo)


def _draw_orbiting_symbols(painter: QPainter, frame: Frame, glow: QColor) -> None:
    """Little stars turning above the hat while Claude reasons."""
    for index in range(3):
        phase = frame.total_time * 1.8 + index * (2.0 * math.pi / 3.0)
        x = _HAT_TIP.x() - 3.0 + math.cos(phase) * 10.0
        y = _HAT_TIP.y() - 2.0 + math.sin(phase) * 3.2
        size = 1.5 + 0.8 * (math.sin(phase) + 1.0) / 2.0
        _star(painter, QPointF(x, y), size, glow)


def _draw_scroll(painter: QPainter, frame: Frame) -> None:
    """He holds out a scroll: something needs your signature."""
    offer = math.sin(frame.total_time * 2.2) * 0.9
    rect = QRectF(15.0, 58.0 + offer, 17.0, 12.0)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(CREAM))
    painter.drawRoundedRect(rect, 1.6, 1.6)

    pen = QPen(QColor(150, 128, 96), 0.9)
    painter.setPen(pen)
    for index in range(3):
        y = rect.top() + 3.4 + index * 2.6
        painter.drawLine(
            QPointF(rect.left() + 2.6, y), QPointF(rect.right() - 2.6, y)
        )
    painter.setPen(Qt.PenStyle.NoPen)

    # Rolled ends, which is what makes it a scroll and not a sheet of paper.
    painter.setBrush(QColor(TERRACOTTA))
    painter.drawRoundedRect(
        QRectF(rect.left() - 1.6, rect.top() - 1.0, 3.2, rect.height() + 2.0), 1.6, 1.6
    )
    painter.drawRoundedRect(
        QRectF(rect.right() - 1.6, rect.top() - 1.0, 3.2, rect.height() + 2.0), 1.6, 1.6
    )
    _hand(painter, QPointF(rect.right() + 1.0, rect.center().y()), 3.0)


def _draw_zzz(painter: QPainter, frame: Frame) -> None:
    """Rising "z"s, drawn as strokes rather than text.

    drawText would be shorter, but it makes the character depend on a font being
    installed and on how that font hints at 10px. A three-stroke z is the same
    shape at every size and on every machine.
    """
    for index in range(2):
        phase = (frame.total_time * 0.55 + index * 0.5) % 1.0
        side = 3.4 + index * 1.6
        x = _HEAD.x() + 15.0 + index * 4.0
        y = _BRIM_Y - 4.0 - phase * 8.0 - index * 3.0
        colour = QColor(CREAM)
        colour.setAlphaF(max(0.0, 1.0 - phase))
        pen = QPen(colour, 1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        zed = QPainterPath()
        zed.moveTo(x, y)
        zed.lineTo(x + side, y)
        zed.lineTo(x, y + side)
        zed.lineTo(x + side, y + side)
        painter.drawPath(zed)
    painter.setPen(Qt.PenStyle.NoPen)


def _draw_sweat(painter: QPainter) -> None:
    drop = QPainterPath()
    top = QPointF(_HEAD.x() + 15.5, _HEAD.y() - 5.0)
    drop.moveTo(top)
    drop.cubicTo(
        QPointF(top.x() + 5.0, top.y() + 6.0),
        QPointF(top.x() + 3.4, top.y() + 11.5),
        QPointF(top.x(), top.y() + 11.5),
    )
    drop.cubicTo(
        QPointF(top.x() - 3.4, top.y() + 11.5),
        QPointF(top.x() - 5.0, top.y() + 6.0),
        top,
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#63C7FF"))
    painter.drawPath(drop)


def _draw_sparkles(painter: QPainter, frame: Frame, glow: QColor) -> None:
    for index, (x, y) in enumerate(((22.0, 30.0), (74.0, 44.0), (30.0, 52.0))):
        phase = (frame.time * 1.6 + index * 0.33) % 1.0
        size = 1.2 + 2.2 * math.sin(phase * math.pi)
        if size <= 0.2:
            continue
        colour = QColor(glow)
        colour.setAlphaF(max(0.0, math.sin(phase * math.pi)))
        _star(painter, QPointF(x, y), size, colour)


def _draw_sound_waves(painter: QPainter, frame: Frame, halo: QColor) -> None:
    """Arcs at his ear, growing with the microphone level."""
    for index in range(3):
        phase = (frame.total_time * 1.7 + index * 0.33) % 1.0
        radius = 5.0 + index * 3.4 + frame.level * 3.0
        colour = QColor(halo)
        colour.setAlphaF(max(0.0, (1.0 - phase) * (0.35 + 0.65 * frame.level)))
        pen = QPen(colour, 1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        centre = QPointF(_HEAD.x() - 17.0, _HEAD.y() + 1.0)
        painter.drawArc(
            QRectF(
                centre.x() - radius, centre.y() - radius, radius * 2.0, radius * 2.0
            ),
            int(120 * 16),
            int(120 * 16),
        )
    painter.setPen(Qt.PenStyle.NoPen)


def _draw_question(painter: QPainter, frame: Frame, halo: QColor) -> None:
    """A question mark built from an arc and a dot, for the same reason as the z."""
    bob = math.sin(frame.total_time * 2.8) * 1.2
    x = _HEAD.x() + 16.0
    y = _BRIM_Y - 8.0 + bob

    pen = QPen(QColor(halo), 1.9)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    hook = QPainterPath()
    hook.moveTo(x - 2.4, y - 0.6)
    hook.cubicTo(
        QPointF(x - 2.2, y - 3.6), QPointF(x + 2.8, y - 3.4), QPointF(x + 2.4, y - 0.8)
    )
    hook.cubicTo(
        QPointF(x + 2.2, y + 1.0), QPointF(x, y + 1.2), QPointF(x, y + 3.0)
    )
    painter.drawPath(hook)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(halo))
    painter.drawEllipse(QPointF(x, y + 5.6), 1.05, 1.05)
