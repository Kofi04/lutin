"""Clipboard history watcher.

Qt gives us QClipboard.dataChanged, which saves us from polling or installing a
clipboard-viewer chain by hand. We only keep text: images and files would blow
up the database for little benefit here.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QClipboard, QGuiApplication

from ..config import ClipboardSettings
from ..storage import Storage


class ClipboardWatcher(QObject):
    """Mirrors clipboard text into storage while enabled."""

    captured = Signal(str)

    def __init__(
        self,
        storage: Storage,
        settings: ClipboardSettings,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._storage = storage
        self._settings = settings
        self._enabled = settings.enabled
        self._suppress = False
        self._holds = 0

        self._clipboard = QGuiApplication.clipboard()
        self._clipboard.dataChanged.connect(self._on_data_changed)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def apply_settings(self, settings: ClipboardSettings) -> None:
        self._settings = settings
        self._enabled = settings.enabled

    def hold(self) -> None:
        """Stop recording until `release`, for operations that borrow the clipboard.

        `_suppress` only covers our own synchronous writes. When we send Ctrl+C
        to another app, *it* writes the clipboard, later, and that change —
        then our restore of the original — would otherwise land in the
        history as if the user had copied them.
        """
        self._holds += 1

    def release(self) -> None:
        self._holds = max(0, self._holds - 1)

    def copy_to_clipboard(self, text: str) -> None:
        """Put text back on the clipboard without re-recording it."""
        self._suppress = True
        try:
            self._clipboard.setText(text, QClipboard.Mode.Clipboard)
        finally:
            self._suppress = False

    def copy_image_to_clipboard(self, png: bytes) -> None:
        """Put a stored image back on the clipboard without re-recording it."""
        from PySide6.QtGui import QImage

        image = QImage.fromData(png)
        if image.isNull():
            return
        self._suppress = True
        try:
            self._clipboard.setImage(image, QClipboard.Mode.Clipboard)
        finally:
            self._suppress = False

    def _on_data_changed(self) -> None:
        if not self._enabled or self._suppress or self._holds:
            return

        mime = self._clipboard.mimeData(QClipboard.Mode.Clipboard)
        if mime is not None and mime.hasImage() and not mime.hasText():
            self._record_image()
            return

        text = self._clipboard.text(QClipboard.Mode.Clipboard)
        if not text or not text.strip():
            return
        if len(text) > self._settings.max_text_length:
            return

        if self._storage.add_clip(text, self._settings.max_entries) is not None:
            self.captured.emit(text)

    def _record_image(self) -> None:
        if not self._settings.images or self._settings.max_images <= 0:
            return
        image = self._clipboard.image(QClipboard.Mode.Clipboard)
        if image.isNull():
            return
        png, thumbnail = encode_image(image)
        added = self._storage.add_image_clip(
            png,
            thumbnail,
            image.width(),
            image.height(),
            self._settings.max_entries,
            self._settings.max_images,
        )
        if added is not None:
            self.captured.emit(f"Image {image.width()}×{image.height()}")


#: Stored copies are capped: a 4K screenshot kept at full size is several
#: megabytes, and the point is to find it again, not to archive it.
MAX_STORED_EDGE = 2560
THUMBNAIL_EDGE = 96


def encode_image(image) -> tuple[bytes, bytes]:
    """The image as stored (capped size) and its thumbnail, both PNG."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt

    def png(source) -> bytes:
        buffer = QBuffer()
        buffer.setData(QByteArray())
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        source.save(buffer, "PNG")
        return bytes(buffer.data())

    stored = image
    if max(image.width(), image.height()) > MAX_STORED_EDGE:
        stored = image.scaled(
            MAX_STORED_EDGE,
            MAX_STORED_EDGE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    thumbnail = image.scaled(
        THUMBNAIL_EDGE,
        THUMBNAIL_EDGE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return png(stored), png(thumbnail)
