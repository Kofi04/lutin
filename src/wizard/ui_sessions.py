"""Mini-wizards beside the main one: one per Claude session in flight.

Each background agent, and each of your own Claude Code sessions reported by
the hooks, gets a small wizard in the pose that matches its state — working,
waiting for your answer, done, failed — ringed in the session's colour and
labelled with its project. Hover for what it did last; click for its menu.

Drawn once per change, not animated. Several sessions can run for an hour;
a timer per mini-wizard would spend the CPU budget on decoration, and the
information is in the pose, not in the motion.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from .character.animation import still_frame
from .character.emote import Emote
from .character.renderer import load_renderer

#: Session state -> pose. Unknown states rest.
POSES = {
    "idle": Emote.IDLE,
    "thinking": Emote.THINKING,
    "working": Emote.WORKING,
    "waiting": Emote.WAITING_APPROVAL,
    "done": Emote.SUCCESS,
    "error": Emote.CONFUSED,
}

STATE_LABELS = {
    "idle": "au repos",
    "thinking": "réfléchit",
    "working": "travaille",
    "waiting": "attend votre accord",
    "done": "terminé",
    "error": "en échec",
}

_FIGURE = 44
_SLOT_W = 58
_HEIGHT = 74
_GAP = 6
#: Past this, the row would cover half the taskbar; the rest is summarised.
MAX_SHOWN = 6


def pose_for(state: str) -> Emote:
    return POSES.get(state, Emote.IDLE)


class SessionDock(QWidget):
    """A row of mini-wizards, kept just left of the main avatar."""

    #: session_id of the mini-wizard that was clicked.
    clicked = Signal(str)

    def __init__(self, anchor: QWidget) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        self.setMouseTracking(True)
        self._anchor = anchor
        self._renderer = load_renderer()
        self._sessions: list = []
        self._hidden_count = 0
        self._suppressed = False

    # -- content ------------------------------------------------------------

    def update_sessions(self, sessions: list) -> None:
        shown = list(sessions)[:MAX_SHOWN]
        self._hidden_count = max(0, len(sessions) - len(shown))
        self._sessions = shown
        if not shown or self._suppressed:
            self.hide()
            return
        slots = len(shown) + (1 if self._hidden_count else 0)
        self.setFixedSize(slots * _SLOT_W + _GAP, _HEIGHT)
        self.reposition()
        self.show()
        self.update()

    def set_suppressed(self, suppressed: bool) -> None:
        """Hide while the main avatar is hidden (full screen, or by the user)."""
        self._suppressed = suppressed
        if suppressed:
            self.hide()
        else:
            self.update_sessions(self._sessions)

    def reposition(self) -> None:
        anchor = self._anchor.geometry()
        x = anchor.left() - self.width() - _GAP
        y = anchor.bottom() - self.height()
        screen = self._anchor.screen()
        if screen is not None:
            area = screen.availableGeometry()
            if x < area.left():
                # No room on the left: sit above the avatar instead.
                x = max(area.left(), anchor.right() - self.width())
                y = anchor.top() - self.height() - _GAP
        self.move(QPoint(x, y))

    # -- drawing ------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = QFont(self.font())
        font.setPointSizeF(7.5)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        for index, session in enumerate(self._sessions):
            left = _GAP + index * _SLOT_W
            colour = QColor(session.colour)

            halo = QColor(colour)
            halo.setAlpha(60)
            painter.setPen(QPen(colour, 2.0))
            painter.setBrush(halo)
            ring = QRectF(left + (_SLOT_W - _FIGURE) / 2 - 3, 2, _FIGURE + 6, _FIGURE + 6)
            painter.drawEllipse(ring)

            painter.save()
            painter.translate(left + (_SLOT_W - _FIGURE) / 2, 4)
            self._renderer.draw(
                painter,
                float(_FIGURE),
                still_frame(pose_for(session.state), shadow=False),
            )
            painter.restore()

            label = metrics.elidedText(
                session.label, Qt.TextElideMode.ElideRight, _SLOT_W - 6
            )
            pill = QRectF(left + 2, _FIGURE + 12, _SLOT_W - 4, 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(20, 22, 31, 200))
            painter.drawRoundedRect(pill, 8, 8)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), label)

        if self._hidden_count:
            left = _GAP + len(self._sessions) * _SLOT_W
            painter.setPen(QColor("#FFFFFF"))
            painter.setBrush(QColor(20, 22, 31, 200))
            box = QRectF(left + 8, 14, _SLOT_W - 16, 26)
            painter.drawRoundedRect(box, 13, 13)
            painter.drawText(
                box, int(Qt.AlignmentFlag.AlignCenter), f"+{self._hidden_count}"
            )
        painter.end()

    # -- pointer ------------------------------------------------------------

    def _session_at(self, x: int):
        index = (x - _GAP) // _SLOT_W
        if 0 <= index < len(self._sessions):
            return self._sessions[index]
        return None

    def mouseMoveEvent(self, event) -> None:
        session = self._session_at(int(event.position().x()))
        if session is None:
            QToolTip.hideText()
            return
        lines = [f"{session.label} — {STATE_LABELS.get(session.state, session.state)}"]
        lines += [f"• {line}" for line in list(session.feed)[-4:]]
        QToolTip.showText(event.globalPosition().toPoint(), "\n".join(lines), self)

    def mousePressEvent(self, event) -> None:
        session = self._session_at(int(event.position().x()))
        if session is not None and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(session.session_id)
        event.accept()
