"""Grab a rectangle of the desktop as an image.

The Tauri overlay draws the selection; the core only receives the rectangle
(logical desktop coordinates) and grabs it, once our windows are out of the
way (cloak.py).
"""

from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QImage


def grab_rect(rect: QRect) -> QImage | None:
    """Grab a rectangle given in global logical coordinates.

    Grabs the whole screen and crops, rather than asking Qt for a sub-rect:
    it keeps the device-pixel-ratio maths in one place and behaves the same on
    every DPI setting.
    """
    if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
        return None

    screen = QGuiApplication.screenAt(rect.center())
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:  # pragma: no cover - no display
        return None

    pixmap = screen.grabWindow(0)
    if pixmap.isNull():
        return None

    ratio = pixmap.devicePixelRatio() or 1.0
    local = rect.translated(-screen.geometry().topLeft())
    device = QRect(
        round(local.x() * ratio),
        round(local.y() * ratio),
        round(local.width() * ratio),
        round(local.height() * ratio),
    )
    device = device.intersected(QRect(0, 0, pixmap.width(), pixmap.height()))
    if device.width() <= 0 or device.height() <= 0:
        return None

    cropped = pixmap.copy(device)
    cropped.setDevicePixelRatio(1.0)  # the image is now plain pixels
    return cropped.toImage()
