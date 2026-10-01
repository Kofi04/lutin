"""Thin ctypes wrappers over the Win32 APIs the avatar needs.

Everything here is stdlib-only on purpose: the handful of calls we make
(taskbar state, system counters, global hotkeys, autostart, window lookup) are
cheap to express with ctypes and not worth an extra dependency.

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


# ---------------------------------------------------------------------------
# Window lookup (for "drop the avatar on a window")
# ---------------------------------------------------------------------------

_GA_ROOT = 2
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass(frozen=True)
class WindowInfo:
    """A top-level window, in physical pixels (what Win32 reports)."""

    hwnd: int
    title: str
    process: str  # executable name, e.g. "chrome.exe"
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def label(self) -> str:
        """Short human label for the context pill, e.g. "Chrome - Gmail"."""
        app = self.process.removesuffix(".exe").replace("_", " ").title()
        title = self.title.strip()
        if not title:
            return app
        if len(title) > 60:
            title = title[:59] + "…"
        return f"{app} — {title}"


def _window_title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, length + 1)
    return buffer.value


def _window_process_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    if not pid.value:
        return ""

    # LIMITED_INFORMATION is enough for the image name and, unlike
    # PROCESS_QUERY_INFORMATION, does not need elevation for most processes.
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(260)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            return ""
        return os.path.basename(buffer.value)
    finally:
        _kernel32.CloseHandle(handle)


def window_at(x: int, y: int, ignore: set[int] | None = None):
    """The top-level window at a physical screen point, or None.

    `ignore` holds our own window handles: the avatar is always-on-top, so
    without this the lookup would always find the avatar itself.
    """
    if not IS_WINDOWS:
        return None

    hwnd = _user32.WindowFromPoint(wintypes.POINT(x, y))
    if not hwnd:
        return None

    # WindowFromPoint returns the deepest child (a button, a text area); walk up
    # to the top-level window the user actually means.
    root = _user32.GetAncestor(wintypes.HWND(hwnd), _GA_ROOT)
    hwnd = int(root) if root else int(hwnd)

    if ignore and hwnd in ignore:
        return None
    if not _user32.IsWindowVisible(wintypes.HWND(hwnd)):
        return None

    rect = wintypes.RECT()
    if not _user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None
    if rect.right <= rect.left or rect.bottom <= rect.top:
        return None

    return WindowInfo(
        hwnd=hwnd,
        title=_window_title(hwnd),
        process=_window_process_name(hwnd),
        left=rect.left,
        top=rect.top,
        right=rect.right,
        bottom=rect.bottom,
    )


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
    return f'"{exe}" -m wizard'


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


def migrate_autostart_value(legacy_name: str) -> bool:
    """Move a Run entry written under the app's old name onto the current one.

    Returns True when it did something. Without this, renaming the app would
    leave a Run entry pointing at `-m lutin`, which no longer imports: Windows
    would try to start the app at every logon and fail silently forever, while
    the tray checkbox showed "start with Windows" as off.
    """
    if not IS_WINDOWS or legacy_name == _RUN_VALUE:
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_WRITE
        ) as key:
            try:
                winreg.QueryValueEx(key, legacy_name)
            except FileNotFoundError:
                return False
            # Re-derive the command rather than reusing the stored one: the old
            # value points at the old module name.
            winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, _launch_command())
            winreg.DeleteValue(key, legacy_name)
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Full-screen detection
# ---------------------------------------------------------------------------

_QUNS_BUSY = 2
_QUNS_RUNNING_D3D_FULL_SCREEN = 3
_QUNS_PRESENTATION_MODE = 4

#: States in which Windows itself suppresses notifications. Borrowing that
#: judgement is better than comparing window rectangles to monitor rectangles,
#: which gets fooled by a maximised window with a hidden taskbar and misses a
#: borderless game that is not technically full-screen.
_QUIET_STATES = frozenset(
    {_QUNS_BUSY, _QUNS_RUNNING_D3D_FULL_SCREEN, _QUNS_PRESENTATION_MODE}
)


def user_notification_state() -> int:
    """`SHQueryUserNotificationState`, or 0 when it cannot be read."""
    if not IS_WINDOWS or _shell32 is None:
        return 0
    state = ctypes.c_int(0)
    try:
        result = _shell32.SHQueryUserNotificationState(ctypes.byref(state))
    except (AttributeError, OSError):
        return 0
    # S_OK is 0; anything else means the answer is not usable.
    return state.value if result == 0 else 0


def should_stay_quiet() -> bool:
    """True when something full-screen is running and we should get out of the way.

    A game, a presentation or a full-screen video is exactly when an always-on
    top avatar is most annoying, and it is also when Windows stops showing its
    own notifications — so this asks Windows rather than guessing.
    """
    return user_notification_state() in _QUIET_STATES


# ---------------------------------------------------------------------------
# Overlay windows: click-through, and hidden from screen capture
# ---------------------------------------------------------------------------

_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_NOACTIVATE = 0x08000000

_WDA_NONE = 0x00000000
#: Windows 10 2004 (build 19041) and later. Older builds reject it, which the
#: caller learns from the return value.
_WDA_EXCLUDEFROMCAPTURE = 0x00000011


def make_click_through(hwnd: int) -> bool:
    """Let every click pass straight through a window to whatever is below.

    Qt's WindowTransparentForInput asks for this, but whether a particular Qt
    build sets WS_EX_TRANSPARENT *and* WS_EX_LAYERED has varied between
    versions. An overlay that swallows one click is an overlay that breaks the
    user's app, so the styles are set explicitly as well.
    """
    if not IS_WINDOWS or not hwnd:
        return False
    handle = wintypes.HWND(hwnd)
    get_long = getattr(_user32, "GetWindowLongPtrW", _user32.GetWindowLongW)
    set_long = getattr(_user32, "SetWindowLongPtrW", _user32.SetWindowLongW)
    style = get_long(handle, _GWL_EXSTYLE)
    wanted = style | _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_NOACTIVATE
    if wanted == style:
        return True
    set_long(handle, _GWL_EXSTYLE, wanted)
    return (get_long(handle, _GWL_EXSTYLE) & _WS_EX_TRANSPARENT) != 0


def exclude_from_capture(hwnd: int, exclude: bool = True) -> bool:
    """Hide a window from screenshots, recordings and screen sharing.

    This is what stops the avatar and the overlay from appearing in the
    captures the app itself sends to Claude. It has a side effect the user
    must know about, and the README says so: the same windows also vanish from
    Teams, Zoom, OBS and every other capture — which is why it is a setting.
    """
    if not IS_WINDOWS or not hwnd:
        return False
    affinity = _WDA_EXCLUDEFROMCAPTURE if exclude else _WDA_NONE
    try:
        return bool(_user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), affinity))
    except (AttributeError, OSError):
        return False


# ---------------------------------------------------------------------------
# Talking to other apps: focus, key presses, the clipboard's sequence number
# ---------------------------------------------------------------------------

_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004

VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_SHIFT = 0x10
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_C = 0x43
VK_V = 0x56

_MODIFIER_VKS = (VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN, VK_RWIN)

_ULONG_PTR = ctypes.c_size_t


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _MOUSEINPUT(ctypes.Structure):
    # Only here so the union has the size Windows expects; SendInput rejects
    # the whole call when cbSize does not match sizeof(INPUT).
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> _INPUT:
    event = _INPUT()
    event.type = _INPUT_KEYBOARD
    event.union.ki = _KEYBDINPUT(vk, scan, flags, 0, 0)
    return event


def send_chord(*vks: int) -> bool:
    """Press the keys in order, then release them in reverse: Ctrl+C, Ctrl+V."""
    if not IS_WINDOWS or not vks:
        return False
    events = [_key(vk) for vk in vks] + [
        _key(vk, flags=_KEYEVENTF_KEYUP) for vk in reversed(vks)
    ]
    array = (_INPUT * len(events))(*events)
    sent = _user32.SendInput(len(events), array, ctypes.sizeof(_INPUT))
    return sent == len(events)


def modifiers_held() -> bool:
    """True while Ctrl, Alt, Shift or Win is physically down.

    A global hotkey fires on key-down, with its modifiers still held. Sending
    Ctrl+C at that moment produces Ctrl+Alt+C — which is this app's own "ask
    Claude" shortcut. Copying the selection has to wait for this to go False.
    """
    if not IS_WINDOWS:
        return False
    return any(_user32.GetAsyncKeyState(vk) & 0x8000 for vk in _MODIFIER_VKS)


def foreground_window() -> int:
    if not IS_WINDOWS:
        return 0
    return int(_user32.GetForegroundWindow() or 0)


def focus_window(hwnd: int) -> bool:
    """Give focus back to the app the selection came from."""
    if not IS_WINDOWS or not hwnd:
        return False
    return bool(_user32.SetForegroundWindow(wintypes.HWND(hwnd)))


def clipboard_sequence() -> int:
    """Increments on every clipboard change, whoever made it."""
    if not IS_WINDOWS:
        return 0
    return int(_user32.GetClipboardSequenceNumber())
