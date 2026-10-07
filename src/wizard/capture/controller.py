"""Turns a capture request into one `Capture`, ready for the preview.

A region (drawn by the Tauri overlay, received as a rectangle), the screen
under the cursor, or a dropped file. The app only listens for `captured`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRect, Signal
from PySide6.QtGui import QImage

from .. import winapi
from .cloak import Cloak
from .grab import grab_rect
from .prepare import CaptureKind, prepare
from .window import capture_window, physical_to_logical

#: Image formats we can show Claude directly. Anything else is reported rather
#: than silently dropped.
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


class CaptureController(QObject):
    """Grabs what was asked for, with our windows out of the way."""

    #: A capture the user has confirmed.
    captured = Signal(object)  # Capture
    #: Something went wrong, with a message fit for a tray notification.
    failed = Signal(str)
    #: A region grabbed for reading its text: full resolution, never sent.
    text_region = Signal(object)  # QImage

    def __init__(self, parent: QObject | None = None, cloak=None) -> None:
        super().__init__(parent)

        # Every grab goes through this: our windows out of the way, a moment
        # for the screen to repaint, then the grab. A RemoteCloak when the
        # windows belong to the Tauri UI.
        self._cloak = cloak if cloak is not None else Cloak()

    # -- region -----------------------------------------------------------

    def grab_region(self, rect: QRect, for_text: bool = False) -> None:
        """Grab a rectangle (logical desktop coordinates) chosen elsewhere."""
        if rect.width() <= 0 or rect.height() <= 0:
            self.failed.emit("Zone vide : rien à capturer.")
            return
        grab = self._grab_text if for_text else self._grab_region
        self._around(lambda: grab(rect))

    def _around(self, action) -> None:
        started = self._cloak.around(
            action,
            on_abort=lambda: self.failed.emit(
                "Capture annulée : l'interface n'a pas pu se cacher à temps."
            ),
        )
        if not started:
            self.failed.emit("Une capture est déjà en cours.")

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
        self._around(lambda: self._grab_screen(rect))

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

    # -- a window -----------------------------------------------------------

    def capture_window_at(self, x: int, y: int) -> None:
        """Ctrl + drag released at this physical point: the window under it."""
        info = winapi.window_at(x, y)
        if info is None:
            self.failed.emit("Aucune fenêtre à cet endroit.")
            return
        rect = physical_to_logical(info.left, info.top, info.right, info.bottom)
        self._around(lambda: self._grab_window(info, rect))

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
