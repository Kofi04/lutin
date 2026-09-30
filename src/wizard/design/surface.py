"""Window materials: Mica and rounded corners on Windows 11, a clean fallback on 10.

`DwmSetWindowAttribute` gained the backdrop and corner attributes in Windows 11
(build 22000); on Windows 10 the calls simply return a failure code, which is
why every one of them is checked rather than fired and forgotten. The fallback
is not a degraded Mica — it is an opaque surface from the tokens with a drawn
border, which is what Windows 10 apps actually look like.

**This module's Windows 11 path is written but unverified**: the machine it was
developed on is Windows 10 22H2 (build 19045). The fallback is the tested path.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from ..winapi import IS_WINDOWS

#: Backdrop and corner attributes both arrived with Windows 11.
WIN11_BUILD = 22000

# DWMWINDOWATTRIBUTE
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_SYSTEMBACKDROP_TYPE = 38

# DWM_WINDOW_CORNER_PREFERENCE
CORNER_DEFAULT = 0
CORNER_SQUARE = 1
CORNER_ROUND = 2
CORNER_ROUND_SMALL = 3

# DWM_SYSTEMBACKDROP_TYPE
BACKDROP_AUTO = 0
BACKDROP_NONE = 1
#: Mica: the desktop wallpaper, heavily blurred. For long-lived windows.
BACKDROP_MICA = 2
#: Acrylic: blurs whatever is behind. For transient surfaces like a palette.
BACKDROP_ACRYLIC = 3
#: Mica Alt, the "tabbed" variant.
BACKDROP_MICA_ALT = 4

_dwmapi = ctypes.WinDLL("dwmapi") if IS_WINDOWS else None


def windows_build() -> int:
    """The current Windows build number, or 0 when that makes no sense."""
    if not IS_WINDOWS:
        return 0
    version = getattr(sys, "getwindowsversion", None)
    if version is None:  # pragma: no cover - Windows always has it
        return 0
    return int(version().build)


def supports_material() -> bool:
    """Whether Mica and native rounded corners exist on this machine."""
    return IS_WINDOWS and windows_build() >= WIN11_BUILD


def _set_attribute(hwnd: int, attribute: int, value: int) -> bool:
    if _dwmapi is None or not hwnd:
        return False
    data = ctypes.c_int(value)
    try:
        result = _dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(attribute),
            ctypes.byref(data),
            ctypes.sizeof(data),
        )
    except OSError:
        return False
    # S_OK is 0. Windows 10 returns E_INVALIDARG for the Windows 11 attributes,
    # which is the signal to fall back rather than an error worth reporting.
    return result == 0


def apply_dark_titlebar(hwnd: int, dark: bool) -> bool:
    """Match the title bar to the theme. Works from Windows 10 1809 on."""
    return _set_attribute(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, int(dark))


def apply_rounded(hwnd: int, small: bool = False) -> bool:
    return _set_attribute(
        hwnd,
        _DWMWA_WINDOW_CORNER_PREFERENCE,
        CORNER_ROUND_SMALL if small else CORNER_ROUND,
    )


def apply_backdrop(hwnd: int, backdrop: int = BACKDROP_MICA) -> bool:
    return _set_attribute(hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, backdrop)


def decorate(widget, dark: bool, backdrop: int = BACKDROP_MICA) -> bool:
    """Give a window the best material this machine can do.

    Returns True when the Windows 11 material was applied, so the caller knows
    whether to paint its own opaque background. Getting that wrong is visible:
    an opaque background over Mica wastes it, and a transparent one without
    Mica is an unreadable hole.
    """
    handle = int(widget.winId())
    apply_dark_titlebar(handle, dark)
    if not supports_material():
        return False
    rounded = apply_rounded(handle)
    material = apply_backdrop(handle, backdrop)
    return bool(rounded and material)
