"""Find the window under the cursor, and capture it.

Win32 reports window rectangles in *physical* pixels while Qt works in logical
ones, so `physical_to_logical` converts before anything is grabbed. That
conversion uses one screen's scale factor, which is exact on a single-DPI
desktop and approximate if two monitors run different scaling.

The capture grabs the screen area the window occupies, so a window hidden
behind another would come out covered: you point at a window you can see.
Nothing calls this since the Qt avatar went (its Ctrl+drag); it stays for the
Tauri avatar to do the same.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QCursor, QGuiApplication, QImage

from .. import winapi
from .grab import grab_rect


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
