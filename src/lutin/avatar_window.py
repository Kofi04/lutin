"""The floating avatar window.

This is the only place that touches window flags and screen geometry. Three
things make it behave like part of the shell rather than an app window:

* `Qt.Tool` keeps it out of the taskbar and out of Alt+Tab;
* `WA_TranslucentBackground` plus `FramelessWindowHint` gives a shaped window;
* `WindowDoesNotAcceptFocus` means clicking the avatar never steals focus from
  whatever you were typing in.

Placement is derived from Qt's `availableGeometry()` rather than from
SHAppBarMessage, because Qt reports it in logical pixels and already accounts
for DPI scaling. The Win32 call is only used for the auto-hide flag, which Qt
does not expose.
"""

from __future__ import annotations

import math
import os
import random
import re

from PySide6.QtCore import QPoint, QPointF, QRect, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from . import winapi
from .branding import APP_NAME
from .config import Appearance, config_dir
from .mood import Mood
from .sprite import BASE_SIZE, SpriteState, draw_avatar

# Frame pacing is adaptive. Nobody is studying the idle bob, and an avatar that
# reports your CPU load has no business adding to it: 10 fps is plenty for a
# three-second breathing cycle, and we only pay for 20 fps while you interact.
_FRAME_MS_IDLE = 100
_FRAME_MS_ACTIVE = 50
_EDGE_MARGIN = 10  # gap between the avatar and the screen edge
_LOOK_RANGE = 320.0  # cursor distance (px) at which the pupils are fully deflected


class AvatarWindow(QWidget):
    """A small always-on-top window that draws the avatar and emits clicks."""

    clicked = Signal()
    context_menu_requested = Signal(QPoint)
    moved_by_user = Signal()

    #: Ctrl+drag: the controller looks up the window under the cursor and shows
    #: the halo. The avatar itself knows nothing about windows or captures.
    targeting_started = Signal()
    targeting_moved = Signal()
    targeting_finished = Signal()
    targeting_cancelled = Signal()

    #: Local file paths dropped onto the avatar.
    files_dropped = Signal(list)

    def __init__(self, appearance: Appearance) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        self.setWindowTitle(APP_NAME)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._appearance = appearance
        self._state = SpriteState()
        self._settings = QSettings(
            str(config_dir() / "state.ini"), QSettings.Format.IniFormat
        )

        self._elapsed = 0.0
        self._next_blink = self._schedule_blink()
        self._blink_started_at: float | None = None

        self._drag_origin: QPoint | None = None
        self._dragged = False
        self._targeting = False
        self.setAcceptDrops(True)

        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS_IDLE)
        self._timer.timeout.connect(self._advance_frame)

        self.apply_appearance(appearance)

    # -- public API -------------------------------------------------------

    def apply_appearance(self, appearance: Appearance) -> None:
        self._appearance = appearance
        side = int(BASE_SIZE * appearance.scale)
        self.setFixedSize(side, side)
        self.setWindowOpacity(appearance.opacity)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            appearance.click_through_when_idle,
        )
        self.restore_position()

    def set_mood(self, mood: Mood) -> None:
        if mood is not self._state.mood:
            self._state.mood = mood
            self.update()

    def restore_position(self) -> None:
        """Put the avatar back where the user left it, or snap to the taskbar."""
        saved = self._settings.value("avatar/position")
        if saved is not None:
            point = _to_point(saved)
            if point is not None and self._is_on_a_screen(point):
                self.move(point)
                return
        self.snap_to_taskbar()

    def snap_to_taskbar(self) -> None:
        """Park the avatar against the taskbar edge, near the notification area."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:  # pragma: no cover - no display
            return

        full = screen.geometry()
        free = screen.availableGeometry()
        edge = _reserved_edge(full, free)

        if edge is None:
            # Nothing reserved: the taskbar is auto-hiding, so fall back to the
            # edge Win32 reports and treat the bar as zero-thickness.
            info = winapi.taskbar_info()
            edge = info.edge if info is not None else winapi.Edge.BOTTOM

        width, height = self.width(), self.height()
        if edge is winapi.Edge.BOTTOM:
            point = QPoint(free.right() - width - _EDGE_MARGIN, free.bottom() - height)
        elif edge is winapi.Edge.TOP:
            point = QPoint(free.right() - width - _EDGE_MARGIN, free.top())
        elif edge is winapi.Edge.LEFT:
            point = QPoint(free.left(), free.bottom() - height - _EDGE_MARGIN)
        else:  # RIGHT
            point = QPoint(free.right() - width, free.bottom() - height - _EDGE_MARGIN)

        point += QPoint(self._appearance.offset_x, self._appearance.offset_y)
        self.move(_clamp_to(point, free, width, height))

    def forget_position(self) -> None:
        self._settings.remove("avatar/position")
        self._settings.sync()
        self.snap_to_taskbar()

    # -- Qt overrides -----------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:
        # No point animating a window nobody can see.
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        draw_avatar(painter, float(min(self.width(), self.height())), self._state)

    def enterEvent(self, event) -> None:
        self._state.hovered = True
        self._timer.setInterval(_FRAME_MS_ACTIVE)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._state.hovered = False
        self._state.look = QPointF(0.0, 0.0)
        self._timer.setInterval(_FRAME_MS_IDLE)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() is not Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        # Ctrl+drag points at a window instead of moving the avatar. Plain drag
        # has always moved it, and people rely on that; a modifier is the only
        # way to fit coucou's "drop me on a window" gesture onto a movable
        # character without making one of the two behaviours unreachable.
        self._targeting = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        self._drag_origin = event.globalPosition().toPoint() - self.pos()
        self._dragged = False
        self._state.pressed = True
        self.update()

        if self._targeting:
            self.targeting_started.emit()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin is None:
            return

        if self._targeting:
            # The avatar stays put while targeting; the halo under the cursor is
            # the feedback, so there is nothing to move here.
            self._dragged = True
            self.targeting_moved.emit()
            return

        target = event.globalPosition().toPoint() - self._drag_origin
        if not self._dragged:
            moved = (target - self.pos()).manhattanLength()
            if moved < QApplication.startDragDistance():
                return  # a shaky click is still a click
            self._dragged = True
        self.move(target)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() is not Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return

        self._state.pressed = False
        self._drag_origin = None
        was_targeting, self._targeting = self._targeting, False
        self.update()

        if was_targeting:
            # A Ctrl+click without movement is a mis-click, not a pick.
            if self._dragged:
                self.targeting_finished.emit()
            else:
                self.targeting_cancelled.emit()
        elif self._dragged:
            self._settings.setValue("avatar/position", self.pos())
            self._settings.sync()
            self.moved_by_user.emit()
        else:
            self.clicked.emit()
        event.accept()

    # -- dropped files ----------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and self._local_paths(event.mimeData()):
            self._state.catching = True
            self.update()
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._state.catching = False
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        paths = self._local_paths(event.mimeData())
        self._state.catching = False
        self.update()
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)

    @staticmethod
    def _local_paths(mime) -> list[str]:
        """Local file paths from a drop, ignoring remote URLs and directories."""
        paths = []
        for url in mime.urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if path and os.path.isfile(path):
                    paths.append(path)
        return paths

    def contextMenuEvent(self, event) -> None:
        self.context_menu_requested.emit(event.globalPos())
        event.accept()

    # -- animation --------------------------------------------------------

    def _schedule_blink(self) -> float:
        return self._elapsed + random.uniform(2.5, 6.5)

    def _advance_frame(self) -> None:
        # Read the interval back rather than assuming it: it changes on hover.
        self._elapsed += self._timer.interval() / 1000.0
        self._state.time = self._elapsed
        self._state.eye_open = self._eye_openness()
        if self._state.hovered:
            self._state.look = self._look_direction()
        self.update()

    def _eye_openness(self) -> float:
        blink_duration = 0.16
        if self._blink_started_at is None:
            if self._elapsed >= self._next_blink:
                self._blink_started_at = self._elapsed
            return 1.0

        progress = (self._elapsed - self._blink_started_at) / blink_duration
        if progress >= 1.0:
            self._blink_started_at = None
            self._next_blink = self._schedule_blink()
            return 1.0
        # One smooth down-up sweep over the blink.
        return abs(math.cos(progress * math.pi))

    def _look_direction(self) -> QPointF:
        delta = QCursor.pos() - self.geometry().center()
        return QPointF(
            max(-1.0, min(1.0, delta.x() / _LOOK_RANGE)),
            max(-1.0, min(1.0, delta.y() / _LOOK_RANGE)),
        )

    # -- helpers ----------------------------------------------------------

    def _is_on_a_screen(self, point: QPoint) -> bool:
        """Guard against a saved position on a monitor that is now unplugged."""
        probe = QRect(point, self.size())
        return any(
            screen.availableGeometry().intersects(probe)
            for screen in QGuiApplication.screens()
        )


def _reserved_edge(full: QRect, free: QRect):
    """Which edge the shell reserved space on, or None if it reserved none."""
    if free.bottom() < full.bottom():
        return winapi.Edge.BOTTOM
    if free.top() > full.top():
        return winapi.Edge.TOP
    if free.left() > full.left():
        return winapi.Edge.LEFT
    if free.right() < full.right():
        return winapi.Edge.RIGHT
    return None


def _clamp_to(point: QPoint, bounds: QRect, width: int, height: int) -> QPoint:
    x = max(bounds.left(), min(point.x(), bounds.right() - width + 1))
    y = max(bounds.top(), min(point.y(), bounds.bottom() - height + 1))
    return QPoint(x, y)


def _to_point(value) -> QPoint | None:
    """QSettings normally hands back a QPoint; tolerate the raw "@Point(x y)" too."""
    if isinstance(value, QPoint):
        return value
    if isinstance(value, str):
        numbers = re.findall(r"-?\d+", value)
        if len(numbers) >= 2:
            return QPoint(int(numbers[0]), int(numbers[1]))
    return None
