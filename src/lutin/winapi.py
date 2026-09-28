"""Thin ctypes wrappers over the Win32 APIs the avatar needs.

Everything here is stdlib-only on purpose: the handful of calls we make
(taskbar state, system counters, global hotkeys, autostart) are cheap to
express with ctypes and not worth an extra dependency.

Importing this module on a non-Windows platform is safe; the functions degrade
to neutral values so the rest of the app and the tests stay portable.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
from ctypes import wintypes
from dataclasses import dataclass
from enum import IntEnum

from .branding import AUTOSTART_VALUE

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
else:  # pragma: no cover - the app only ships on Windows
    _user32 = _kernel32 = _shell32 = None


# ---------------------------------------------------------------------------
# Taskbar
# ---------------------------------------------------------------------------


class Edge(IntEnum):
    """Screen edge the taskbar is docked to (matches the ABE_* constants)."""

    LEFT = 0
    TOP = 1
    RIGHT = 2
    BOTTOM = 3


class _APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", wintypes.RECT),
        ("lParam", wintypes.LPARAM),
    ]


_ABM_GETSTATE = 0x00000004
_ABM_GETTASKBARPOS = 0x00000005
_ABS_AUTOHIDE = 0x01


@dataclass(frozen=True)
class TaskbarInfo:
    """Taskbar geometry in *physical* pixels, plus its auto-hide state."""

    edge: Edge
    left: int
    top: int
    right: int
    bottom: int
    auto_hide: bool

    @property
    def thickness(self) -> int:
        if self.edge in (Edge.TOP, Edge.BOTTOM):
            return self.bottom - self.top
        return self.right - self.left


def taskbar_info():
    """Query the taskbar via SHAppBarMessage, or None if unavailable.

    The rect comes back in physical pixels while Qt works in logical ones, so
    prefer QScreen.availableGeometry() for placement maths and use this mainly
    for the auto-hide flag, which Qt does not expose.
    """
    if not IS_WINDOWS:
        return None

    data = _APPBARDATA()
    data.cbSize = ctypes.sizeof(_APPBARDATA)
    if not _shell32.SHAppBarMessage(_ABM_GETTASKBARPOS, ctypes.byref(data)):
        return None

    state_data = _APPBARDATA()
    state_data.cbSize = ctypes.sizeof(_APPBARDATA)
    state = _shell32.SHAppBarMessage(_ABM_GETSTATE, ctypes.byref(state_data))

    return TaskbarInfo(
        edge=Edge(data.uEdge),
        left=data.rc.left,
        top=data.rc.top,
        right=data.rc.right,
        bottom=data.rc.bottom,
        auto_hide=bool(state & _ABS_AUTOHIDE),
    )


# ---------------------------------------------------------------------------
# System counters -> avatar mood
# ---------------------------------------------------------------------------


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


def memory_load_percent() -> float:
    """Percentage of physical RAM currently in use, 0-100."""
    if not IS_WINDOWS:
        return 0.0
    status = _MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    if not _kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0.0
    return float(status.dwMemoryLoad)


@dataclass(frozen=True)
class BatteryState:
    percent: int | None  # None when the machine has no battery
    on_ac: bool


_BATTERY_PERCENT_UNKNOWN = 255
_AC_LINE_UNKNOWN = 255
_BATTERY_FLAG_NO_SYSTEM_BATTERY = 128


def battery_state() -> BatteryState:
    if not IS_WINDOWS:
        return BatteryState(percent=None, on_ac=True)

    status = _SYSTEM_POWER_STATUS()
    if not _kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return BatteryState(percent=None, on_ac=True)

    no_battery = bool(status.BatteryFlag & _BATTERY_FLAG_NO_SYSTEM_BATTERY)
    percent = None
    if not no_battery and status.BatteryLifePercent != _BATTERY_PERCENT_UNKNOWN:
        percent = int(status.BatteryLifePercent)

    ac = status.ACLineStatus
    return BatteryState(percent=percent, on_ac=ac == 1 or ac == _AC_LINE_UNKNOWN)


def _filetime_to_int(ft) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


class CpuSampler:
    """Turns GetSystemTimes snapshots into a CPU usage percentage.

    The Win32 call reports cumulative counters, so a single reading means
    nothing: usage is the delta between two samples. The first sample()
    therefore returns 0.0 and only primes the baseline.
    """

    def __init__(self) -> None:
        self._prev_idle = 0
        self._prev_total = 0
        self._primed = False

    def sample(self) -> float:
        if not IS_WINDOWS:
            return 0.0

        idle = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not _kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return 0.0

        idle_ticks = _filetime_to_int(idle)
        # `kernel` already includes idle time, so the total is kernel + user.
        total_ticks = _filetime_to_int(kernel) + _filetime_to_int(user)

        d_idle = idle_ticks - self._prev_idle
        d_total = total_ticks - self._prev_total
        self._prev_idle, self._prev_total = idle_ticks, total_ticks

        if not self._primed:
            self._primed = True
            return 0.0
        if d_total <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total)))


# ---------------------------------------------------------------------------
# Global hotkeys
# ---------------------------------------------------------------------------

WM_HOTKEY = 0x0312

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_MODIFIER_NAMES = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "meta": MOD_WIN,
}

# Virtual-key codes for the non-alphanumeric keys worth binding.
_VK_NAMES = {
    "space": 0x20,
    "tab": 0x09,
    "escape": 0x1B,
    "esc": 0x1B,
    "enter": 0x0D,
    "return": 0x0D,
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
}
_VK_NAMES.update({f"f{i}": 0x70 + i - 1 for i in range(1, 25)})


class HotkeyError(ValueError):
    """Raised when a hotkey string cannot be parsed."""


def parse_hotkey(spec: str) -> tuple[int, int]:
    """Parse e.g. "ctrl+alt+N" into (modifiers, virtual-key code).

    Raises HotkeyError on an unknown modifier or key so that a typo in
    config.toml surfaces as a clear message instead of a silently dead
    shortcut.
    """
    parts = [part.strip().lower() for part in spec.split("+") if part.strip()]
    if not parts:
        raise HotkeyError(f"empty hotkey: {spec!r}")

    *modifier_parts, key = parts
    modifiers = MOD_NOREPEAT
    for part in modifier_parts:
        if part not in _MODIFIER_NAMES:
            raise HotkeyError(f"unknown modifier {part!r} in {spec!r}")
        modifiers |= _MODIFIER_NAMES[part]

    if key in _VK_NAMES:
        return modifiers, _VK_NAMES[key]
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        return modifiers, ord(key.upper())
    raise HotkeyError(f"unknown key {key!r} in {spec!r}")


def register_hotkey(hwnd: int, hotkey_id: int, modifiers: int, vk: int) -> bool:
    if not IS_WINDOWS:
        return False
    return bool(_user32.RegisterHotKey(wintypes.HWND(hwnd), hotkey_id, modifiers, vk))


def unregister_hotkey(hwnd: int, hotkey_id: int) -> None:
    if IS_WINDOWS:
        _user32.UnregisterHotKey(wintypes.HWND(hwnd), hotkey_id)


def set_app_user_model_id(app_id: str) -> None:
    """Give the process its own shell identity.

    Without this, Windows attributes our tray notifications to "python.exe";
    with it they show up as the app itself.
    """
    if not IS_WINDOWS:
        return
    # Cosmetic only - never worth failing startup over.
    with contextlib.suppress(AttributeError, OSError):
        _shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))


# ---------------------------------------------------------------------------
# Autostart
# ---------------------------------------------------------------------------

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = AUTOSTART_VALUE


def _launch_command() -> str:
    """The command line that relaunches the app, quoted for the registry."""
    if getattr(sys, "frozen", False):  # PyInstaller build
        return f'"{sys.executable}"'

    # Prefer pythonw.exe so no console window flashes at logon.
    exe = sys.executable
    windowed = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(windowed):
        exe = windowed
    return f'"{exe}" -m lutin'


def autostart_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _RUN_VALUE)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    """Add or remove the HKCU Run entry. No-op off Windows."""
    if not IS_WINDOWS:
        return
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, _launch_command())
        else:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(key, _RUN_VALUE)
