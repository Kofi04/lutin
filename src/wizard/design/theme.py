"""Following Windows: light or dark, and the user's accent colour.

Windows exposes both through the registry rather than through any Qt API, and
it announces changes with a `WM_SETTINGCHANGE` broadcast. Qt 6.5+ also reports
the colour scheme via `QStyleHints.colorScheme()`, which is used when it is
available and trusted over our own reading, because it accounts for the
per-application override that the registry does not show.

Everything degrades to the dark theme off Windows and on a locked-down machine,
which is also what the tests exercise.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication

from ..winapi import IS_WINDOWS
from .tokens import DARK_THEME, LIGHT_THEME, Theme

_PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_DWM = r"Software\Microsoft\Windows\DWM"


def windows_prefers_dark() -> bool:
    """True when apps should be dark. Defaults to dark when unknown."""
    if not IS_WINDOWS:
        return True
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return not bool(value)
    except OSError:
        return True


def windows_accent() -> str | None:
    """The user's accent colour as #RRGGBB, or None if it cannot be read."""
    if not IS_WINDOWS:
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _DWM) as key:
            value, _ = winreg.QueryValueEx(key, "AccentColor")
    except OSError:
        return None

    # DWM stores AABBGGRR, not ARGB: the channels are reversed.
    blue = (value >> 16) & 0xFF
    green = (value >> 8) & 0xFF
    red = value & 0xFF
    return f"#{red:02X}{green:02X}{blue:02X}"


#: The two candidates for text drawn on the accent.
_ON_ACCENT_DARK = "#10131C"
_ON_ACCENT_LIGHT = "#FFFFFF"

#: WCAG AA for normal-sized text.
MIN_CONTRAST = 4.5


def relative_luminance(colour: str) -> float:
    """WCAG relative luminance, which is not the same as HSL lightness."""
    rgb = QColor(colour)
    channels = []
    for value in (rgb.redF(), rgb.greenF(), rgb.blueF()):
        channels.append(
            value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two colours, 1.0 to 21.0."""
    first, second = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def readable_on(colour: str) -> str:
    """Black or white, whichever actually contrasts better against `colour`.

    An accent colour is whatever the user picked, and some of those are pale
    yellow. A luminance cutoff gets the easy cases right and the mid-tones
    wrong, so this measures both candidates instead of guessing at a threshold.
    """
    if contrast(_ON_ACCENT_LIGHT, colour) >= contrast(_ON_ACCENT_DARK, colour):
        return _ON_ACCENT_LIGHT
    return _ON_ACCENT_DARK


def legible_fill(colour: str, minimum: float = MIN_CONTRAST) -> str:
    """Nudge a fill colour until text on it clears the contrast bar.

    Some perfectly ordinary accent colours cannot carry readable text at all:
    Windows' own default blue, #0078D7, tops out at 4.499 against white and
    worse against black, so *no* text passes AA on it. Rather than lower the
    bar or override the user's choice outright, the fill is darkened (or
    lightened) in small steps until it works — close enough to stay recognisably
    their colour, far enough to be readable.
    """
    best = readable_on(colour)
    if contrast(best, colour) >= minimum:
        return colour

    # Move away from whichever side the text is on.
    towards_dark = best == _ON_ACCENT_LIGHT
    current = QColor(colour)
    for _ in range(24):
        current = current.darker(106) if towards_dark else current.lighter(106)
        candidate = current.name()
        if contrast(readable_on(candidate), candidate) >= minimum:
            return candidate
    return colour


def theme_for(dark: bool, accent: str | None = None) -> Theme:
    """Build the theme: a base palette, re-tinted with the system accent."""
    theme = DARK_THEME if dark else LIGHT_THEME
    if not accent:
        return theme

    if not QColor(accent).isValid():
        return theme

    # Text sits on this colour, so it has to be able to carry text.
    base = QColor(legible_fill(accent))
    hover = base.lighter(115) if dark else base.darker(112)
    # A wash, not the accent itself: selected rows must not shout.
    soft = _blend(QColor(base), QColor(theme.palette.surface), 0.78 if dark else 0.84)
    return theme.with_accent(
        accent=base.name(),
        hover=hover.name(),
        soft=soft.name(),
        on_accent=readable_on(base.name()),
    )


def _blend(colour: QColor, into: QColor, amount: float) -> QColor:
    return QColor(
        round(colour.red() + (into.red() - colour.red()) * amount),
        round(colour.green() + (into.green() - colour.green()) * amount),
        round(colour.blue() + (into.blue() - colour.blue()) * amount),
    )


class ThemeWatcher(QObject):
    """Holds the current theme and re-reads it when Windows changes.

    Qt already delivers a signal for the colour scheme; the accent colour has
    none, so it is re-read whenever the scheme changes and on demand. That
    covers the case people actually notice (switching light/dark) without a
    polling timer running all day for the one they do not (changing the accent
    while the app is open).
    """

    changed = Signal(object)  # Theme

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._follow_system = True
        self._theme = self._read()

        hints = QGuiApplication.styleHints()
        if hints is not None and hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda _scheme: self.refresh())

    @property
    def theme(self) -> Theme:
        return self._theme

    def set_follow_system(self, follow: bool, dark: bool = True) -> None:
        """Pin the theme, or go back to following Windows."""
        self._follow_system = follow
        if not follow:
            self._apply(theme_for(dark, windows_accent()))
        else:
            self.refresh()

    def refresh(self) -> None:
        self._apply(self._read())

    def _read(self) -> Theme:
        return theme_for(self._prefers_dark(), windows_accent())

    def _prefers_dark(self) -> bool:
        hints = QGuiApplication.styleHints()
        scheme = getattr(hints, "colorScheme", None)
        if scheme is not None:
            value = scheme()
            # Unknown means Qt has no opinion; fall through to the registry
            # rather than guessing light.
            if value == Qt.ColorScheme.Dark:
                return True
            if value == Qt.ColorScheme.Light:
                return False
        return windows_prefers_dark()

    def _apply(self, theme: Theme) -> None:
        if theme == self._theme:
            return
        self._theme = theme
        self.changed.emit(theme)
