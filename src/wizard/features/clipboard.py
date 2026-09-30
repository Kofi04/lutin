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

    def copy_to_clipboard(self, text: str) -> None:
        """Put text back on the clipboard without re-recording it."""
        self._suppress = True
        try:
            self._clipboard.setText(text, QClipboard.Mode.Clipboard)
        finally:
            self._suppress = False

    def _on_data_changed(self) -> None:
        if not self._enabled or self._suppress:
            return

        text = self._clipboard.text(QClipboard.Mode.Clipboard)
        if not text or not text.strip():
            return
        if len(text) > self._settings.max_text_length:
            return

        if self._storage.add_clip(text, self._settings.max_entries) is not None:
            self.captured.emit(text)
