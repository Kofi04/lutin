"""The design system: tokens, theme, stylesheet, window materials, motion.

Nothing outside this package should name a colour or a pixel size.
"""

from .motion import animate, animations_enabled, fade_in, fade_out
from .qss import stylesheet
from .theme import ThemeWatcher, theme_for, windows_accent, windows_prefers_dark
from .tokens import DARK_THEME, LIGHT_THEME, MOTION, RADIUS, SPACING, TYPE, Theme

__all__ = [
    "DARK_THEME",
    "LIGHT_THEME",
    "MOTION",
    "RADIUS",
    "SPACING",
    "TYPE",
    "Theme",
    "ThemeWatcher",
    "animate",
    "animations_enabled",
    "fade_in",
    "fade_out",
    "stylesheet",
    "theme_for",
    "windows_accent",
    "windows_prefers_dark",
]
