"""Turns the three capture gestures into one confirmed `Capture`.

Everything that knows about screens, windows and halos lives here, so the
avatar window only has to say "the user started pointing" and the app only has
to listen for `captured`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QImage

from .cloak import Cloak
from .prepare import CaptureKind, prepare
from .region import RegionSelector, grab_rect
from .window import (
    WindowHighlight,
    capture_window,
    physical_to_logical,
    window_under_cursor,
)

#: Image formats we can show Claude directly. Anything else is reported rather
#: than silently dropped.
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


class CaptureController(QObject):
    """Owns the selection overlay, the window halo and the preview flow."""

    #: A capture the user has confirmed.
    captured = Signal(object)  # Capture
    #: Something went wrong, with a message fit for a tray notification.
    failed = Signal(str)
    #: A region grabbed for reading its text: full resolution, never sent.
    text_region = Signal(object)  # QImage

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self._selector = RegionSelector(self)
        self._selector.selected.connect(self._on_region_selected)
        # Every grab goes through this: our windows out of the way, a moment
        # for the screen to repaint, then the grab.
        self._cloak = Cloak()

        self._halo = WindowHighlight()
        self._ignored_hwnds: set[int] = set()
        self._target = None

    # -- registration -----------------------------------------------------

    def ignore_window(self, widget) -> None:
        """Never target one of our own windows (the avatar is always-on-top)."""
        handle = int(widget.winId())
        if handle:
            self._ignored_hwnds.add(handle)

    def hide_during_capture(self, widget) -> None:
        """Keep one of our windows out of the screenshots we take."""
        self._cloak.add(widget)

    # -- region -----------------------------------------------------------

    def start_region(self) -> None:
        if not self._selector.active:
            self._for_text = False
            self._selector.start()

    def start_text_region(self) -> None:
        """Select a region to read its text locally, not to show Claude."""
        if not self._selector.active:
            self._for_text = True
            self._selector.start()

    def _on_region_selected(self, rect: QRect) -> None:
        if getattr(self, "_for_text", False):
            self._for_text = False
            self._cloak.around(lambda: self._grab_text(rect))
            return
        self._cloak.around(lambda: self._grab_region(rect))

    def _grab_text(self, rect: QRect) -> None:
        # Full resolution on purpose: the 1568 px downscale that suits
        # Claude would blur small interface text past what OCR can read.
        image = grab_rect(rect)
        if image is None or image.isNull():
            self.failed.emit("Impossible de capturer cette zone.")
            return
        self.text_region.emit(image)

    def _grab_region(self, rect: QRect) -> None:
        image = grab_rect(rect)
        if image is None or image.isNull():
            self.failed.emit("Impossible de capturer cette zone.")
            return
        self._emit(
            image,
            CaptureKind.REGION,
            f"Zone {rect.width()}×{rect.height()}",
            _region_of(rect),
        )

    # -- the whole screen -------------------------------------------------

    def capture_active_screen(self) -> None:
        """Grab the monitor under the cursor, no selection needed."""
        from PySide6.QtGui import QCursor, QGuiApplication

        screen = (
            QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        )
        if screen is None:
            self.failed.emit("Aucun écran disponible.")
            return
        rect = screen.geometry()
        self._cloak.around(lambda: self._grab_screen(rect))

    def _grab_screen(self, rect: QRect) -> None:
        image = grab_rect(rect)
        if image is None or image.isNull():
            self.failed.emit("Impossible de capturer l'écran.")
            return
        self._emit(
            image,
            CaptureKind.SCREEN,
            f"Écran {rect.width()}×{rect.height()}",
            _region_of(rect),
        )

    # -- window -----------------------------------------------------------

    def start_targeting(self) -> None:
        self._ignored_hwnds.add(int(self._halo.winId()))
        self.update_target()

    def update_target(self) -> None:
        """Follow the cursor and frame whatever window is under it."""
        info = window_under_cursor(self._ignored_hwnds)
        self._target = info
        if info is None:
            self._halo.hide_halo()
            return
        self._halo.show_around(
            physical_to_logical(info.left, info.top, info.right, info.bottom)
        )

    def cancel_targeting(self) -> None:
        self._halo.hide_halo()
        self._target = None

    def finish_targeting(self) -> None:
        info, self._target = self._target, None
        self._halo.hide_halo()

        if info is None:
            self.failed.emit("Aucune fenêtre sous le curseur.")
            return

        rect = physical_to_logical(info.left, info.top, info.right, info.bottom)
        self._cloak.around(lambda: self._grab_window(info, rect))

    def _grab_window(self, info, rect: QRect) -> None:
        image = capture_window(info)
        if image is None or image.isNull():
            self.failed.emit(f"Impossible de capturer {info.process or 'la fenêtre'}.")
            return
        self._emit(image, CaptureKind.WINDOW, info.label(), _region_of(rect))

    # -- files ------------------------------------------------------------

    def capture_file(self, path: str) -> None:
        """Load a dropped image file as a capture."""
        suffix = Path(path).suffix.lower()
        if suffix not in _IMAGE_SUFFIXES:
            self.failed.emit(
                f"Je ne sais pas encore lire {suffix or 'ce format'} — "
                "images seulement pour l'instant."
            )
            return

        image = QImage(path)
        if image.isNull():
            self.failed.emit(f"Fichier illisible : {Path(path).name}")
            return
        self._emit(image, CaptureKind.FILE, Path(path).name)

    # -- shared -----------------------------------------------------------

    def _emit(
        self,
        image: QImage,
        kind: CaptureKind,
        label: str,
        region: tuple[float, float, float, float] | None = None,
    ) -> None:
        try:
            capture = prepare(image, kind, label, region=region)
        except (ValueError, RuntimeError) as exc:
            self.failed.emit(str(exc))
            return
        self.captured.emit(capture)


def _region_of(rect: QRect) -> tuple[float, float, float, float]:
    """A logical QRect as the plain tuple the mapping layer works in."""
    return (float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()))
