"""Select a rectangle of the screen, the way a screenshot tool does.

One translucent overlay is created per screen so the interaction works on a
multi-monitor desktop. The overlays must be hidden *before* the grab, or the
capture contains our own dark veil; `_grab_after_repaint` handles that delay.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import QWidget

_VEIL = QColor(12, 14, 18, 150)
_ACCENT = QColor("#5EDCCF")
_MIN_SIDE = 6  # below this the user meant to click, not to select

# Windows needs a moment to actually repaint the desktop after our overlays
# hide. Grabbing immediately captures the veil that is still on screen.
_REPAINT_DELAY_MS = 80


class _ScreenOverlay(QWidget):
    """The veil over one screen. Reports the selection in global coordinates."""

    selected = Signal(QRect)
    cancelled = Signal()

    def __init__(self, screen) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())

        self._origin: QPoint | None = None
        self._current: QPoint | None = None

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.cancelled.emit)

    # -- geometry ---------------------------------------------------------

    def _selection(self) -> QRect:
        if self._origin is None or self._current is None:
            return QRect()
        return QRect(self._origin, self._current).normalized()

    def global_selection(self) -> QRect:
        local = self._selection()
        if local.isNull():
            return QRect()
        return QRect(self.mapToGlobal(local.topLeft()), local.size())

    # -- painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), _VEIL)

        selection = self._selection()
        if selection.width() < 1 or selection.height() < 1:
            return

        # Punch the selection out of the veil so the user sees the real pixels.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(selection, Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        painter.setPen(QPen(_ACCENT, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(selection.adjusted(0, 0, -1, -1))

        self._draw_size_label(painter, selection)

    def _draw_size_label(self, painter: QPainter, selection: QRect) -> None:
        text = f"{selection.width()} × {selection.height()}"
        metrics = painter.fontMetrics()
        box = metrics.boundingRect(text).adjusted(-8, -4, 8, 4)

        # Above the selection, or inside it when there is no room above.
        top = selection.top() - box.height() - 6
        if top < self.rect().top():
            top = selection.top() + 6
        box.moveTo(selection.left(), top)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(12, 14, 18, 220))
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(QColor("#E6EDF3"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    # -- interaction ------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()
        else:
            self.cancelled.emit()

    def mouseMoveEvent(self, event) -> None:
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() is not Qt.MouseButton.LeftButton or self._origin is None:
            return
        selection = self._selection()
        if selection.width() < _MIN_SIDE or selection.height() < _MIN_SIDE:
            self.cancelled.emit()
            return
        self.selected.emit(self.global_selection())


class RegionSelector(QObject):
    """Drives one overlay per screen and grabs whatever the user framed."""

    captured = Signal(QImage, QRect)
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._overlays: list[_ScreenOverlay] = []

    @property
    def active(self) -> bool:
        return bool(self._overlays)

    def start(self) -> None:
        if self._overlays:
            return  # already selecting

        for screen in QGuiApplication.screens():
            overlay = _ScreenOverlay(screen)
            overlay.selected.connect(self._on_selected)
            overlay.cancelled.connect(self._on_cancelled)
            overlay.show()
            overlay.raise_()
            overlay.activateWindow()
            self._overlays.append(overlay)

    def _close_overlays(self) -> None:
        for overlay in self._overlays:
            overlay.hide()
            overlay.close()
        self._overlays.clear()

    def _on_cancelled(self) -> None:
        self._close_overlays()
        self.cancelled.emit()

    def _on_selected(self, rect: QRect) -> None:
        self._close_overlays()
        QTimer.singleShot(_REPAINT_DELAY_MS, lambda: self._grab_after_repaint(rect))

    def _grab_after_repaint(self, rect: QRect) -> None:
        image = grab_rect(rect)
        if image is None or image.isNull():
            self.cancelled.emit()
            return
        self.captured.emit(image, rect)


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
