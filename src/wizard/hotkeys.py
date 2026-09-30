"""System-wide hotkeys, bridged from Win32 into the Qt event loop.

RegisterHotKey posts WM_HOTKEY to a window's message queue, and Qt owns that
queue. QAbstractNativeEventFilter is the supported hook for peeking at raw
messages before Qt translates them, so we install one filter and dispatch from
there. A dedicated never-shown widget owns the registrations, so hotkeys keep
working while the avatar itself is hidden.
"""

from __future__ import annotations

from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QWidget

from . import winapi
from .branding import APP_NAME

_WINDOWS_MSG = b"windows_generic_MSG"


class GlobalHotkeys(QAbstractNativeEventFilter):
    """Registers hotkeys and calls the matching callback when one fires."""

    def __init__(self) -> None:
        super().__init__()

        # An offscreen widget purely to own an HWND for the registrations.
        self._owner = QWidget()
        self._owner.setWindowTitle(f"{APP_NAME} hotkeys")
        self._hwnd = int(self._owner.winId())

        self._next_id = 1
        self._callbacks: dict[int, object] = {}
        self._failures: list[str] = []

    @property
    def failures(self) -> list[str]:
        """Human-readable reasons some hotkeys could not be bound."""
        return list(self._failures)

    def register(self, spec: str, callback) -> bool:
        """Bind `spec` (e.g. "ctrl+alt+N"); returns False and records why if not."""
        if not spec or not spec.strip():
            return False
        try:
            modifiers, vk = winapi.parse_hotkey(spec)
        except winapi.HotkeyError as exc:
            self._failures.append(str(exc))
            return False

        hotkey_id = self._next_id
        if not winapi.register_hotkey(self._hwnd, hotkey_id, modifiers, vk):
            # Almost always because another app already owns the combination.
            self._failures.append(f"{spec} is already taken by another app")
            return False

        self._next_id += 1
        self._callbacks[hotkey_id] = callback
        return True

    def unregister_all(self) -> None:
        for hotkey_id in list(self._callbacks):
            winapi.unregister_hotkey(self._hwnd, hotkey_id)
        self._callbacks.clear()
        # Failures describe the current binding attempt only, so a reload that
        # fixes a typo should not keep reporting the old one.
        self._failures.clear()

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt naming
        if event_type == _WINDOWS_MSG:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == winapi.WM_HOTKEY:
                callback = self._callbacks.get(int(msg.wParam))
                if callback is not None:
                    callback()
                    return True, 0
        return False, 0
