"""In-app notifications, instead of the tray's balloon tips.

Balloons are inconsistent (Windows 10 and 11 render them differently), easy to
miss, silently suppressed by Focus Assist, and impossible to style. These are
ours: they follow the theme, stack above one another near the avatar, and go
away on a click.

They deliberately do *not* replace the approval card. A toast is something you
may ignore; an approval holds a Claude Code session open and must be answered,
so it stays a window that takes focus.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .design import MOTION, SPACING, fade_in, fade_out
from .design.tokens import Theme

#: How long each kind stays up. A warning earns more reading time; nothing
#: stays forever, because a toast you must dismiss is a dialog in disguise.
LIFETIMES_MS = {"info": 4500, "success": 4000, "warning": 8000}

_WIDTH = 340
_GAP = 10
_MARGIN = 16
#: More than this on screen at once is a wall of text nobody reads.
_MAX_VISIBLE = 3


@dataclass(frozen=True)
class Notice:
    title: str
    body: str = ""
    kind: str = "info"

    def lifetime(self) -> int:
        return LIFETIMES_MS.get(self.kind, LIFETIMES_MS["info"])


class Toast(QWidget):
    """One notification."""

    closed = Signal(object)  # Toast

    def __init__(self, notice: Notice, theme: Theme, parent: QWidget | None = None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Never steal focus: a notification that interrupts typing is worse
        # than no notification.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.notice = notice

        palette = theme.palette
        accent = {
            "info": palette.accent,
            "success": palette.success,
            "warning": palette.warning,
        }.get(notice.kind, palette.accent)

        card = QWidget(self)
        card.setObjectName("toastCard")
        card.setStyleSheet(
            f"#toastCard {{"
            f" background: {palette.surface_raised};"
            f" border: 1px solid {palette.border};"
            f" border-left: 3px solid {accent};"
            f" border-radius: {theme.radius.lg}px; }}"
        )

        title = QLabel(notice.title, card)
        title.setStyleSheet(
            f"color: {palette.text}; font-weight: 600;"
            f" font-size: {theme.type.body_large}px; background: transparent;"
        )
        title.setWordWrap(True)

        close = QPushButton("×", card)
        close.setFixedSize(22, 22)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f" color: {palette.text_faint}; font-size: 15px; }}"
            f"QPushButton:hover {{ color: {palette.text}; }}"
        )
        close.clicked.connect(self.dismiss)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(title, 1)
        head.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        inner = QVBoxLayout(card)
        inner.setContentsMargins(
            SPACING.md, SPACING.md, SPACING.sm, SPACING.md
        )
        inner.setSpacing(SPACING.xs)
        inner.addLayout(head)

        if notice.body:
            body = QLabel(notice.body, card)
            body.setWordWrap(True)
            body.setStyleSheet(
                f"color: {palette.text_muted};"
                f" font-size: {theme.type.body}px; background: transparent;"
            )
            inner.addWidget(body)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(Qt.GlobalColor.black)
        card.setGraphicsEffect(shadow)

        self.setFixedWidth(_WIDTH)
        self.adjustSize()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(notice.lifetime())
        self._timer.timeout.connect(self.dismiss)

    def show_toast(self) -> None:
        fade_in(self, MOTION.quick)
        self._timer.start()

    def dismiss(self) -> None:
        if not self.isVisible():
            return
        self._timer.stop()
        fade_out(self, MOTION.quick, then=lambda: self.closed.emit(self))

    def mousePressEvent(self, event) -> None:
        # Clicking anywhere dismisses: nobody hunts for the little cross.
        self.dismiss()
        event.accept()

    def enterEvent(self, event) -> None:
        # Stop the clock while it is being read.
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self.isVisible():
            self._timer.start()
        super().leaveEvent(event)


class ToastManager:
    """Stacks toasts above the avatar and retires them in order."""

    def __init__(self, theme: Theme) -> None:
        self._theme = theme
        self._live: list[Toast] = []
        self._queue: deque[Notice] = deque()
        self._anchor: QWidget | None = None

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme

    def set_anchor(self, widget: QWidget | None) -> None:
        """Stack above this widget (the avatar), or in the screen corner."""
        self._anchor = widget

    def show(self, title: str, body: str = "", kind: str = "info") -> None:
        notice = Notice(title=title, body=body, kind=kind)
        if len(self._live) >= _MAX_VISIBLE:
            self._queue.append(notice)
            return
        self._present(notice)

    def _present(self, notice: Notice) -> None:
        toast = Toast(notice, self._theme)
        toast.closed.connect(self._retire)
        self._live.append(toast)
        self._reposition()
        toast.show_toast()

    def _retire(self, toast: Toast) -> None:
        if toast in self._live:
            self._live.remove(toast)
        toast.deleteLater()
        self._reposition()
        if self._queue and len(self._live) < _MAX_VISIBLE:
            self._present(self._queue.popleft())

    def _reposition(self) -> None:
        origin = self._origin()
        if origin is None:
            return
        bottom = origin.y()
        for toast in reversed(self._live):
            toast.move(QPoint(origin.x() - toast.width(), bottom - toast.height()))
            bottom -= toast.height() + _GAP

    def _origin(self) -> QPoint | None:
        """Bottom-right corner to stack up from."""
        if self._anchor is not None and self._anchor.isVisible():
            geometry = self._anchor.geometry()
            return QPoint(geometry.left() - _GAP, geometry.bottom())

        screen = (
            QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        )
        if screen is None:  # pragma: no cover - no display
            return None
        area = screen.availableGeometry()
        return QPoint(area.right() - _MARGIN, area.bottom() - _MARGIN)

    def clear(self) -> None:
        self._queue.clear()
        for toast in list(self._live):
            toast.dismiss()
