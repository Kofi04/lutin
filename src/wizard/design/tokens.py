"""The design system's vocabulary: colours, spacing, radii, type, motion.

Every colour and every size in the interface comes from here. Before this
module the same GitHub-dark stylesheet was pasted into four files and drifted,
so a change meant finding all four and a theme was impossible.

Two rules keep it honest:

* **Nothing else hard-codes a colour or a pixel size.** If a widget needs a
  value that is not here, the value belongs here.
* **Tokens are semantic, not literal.** `surface`, `text_muted` and `danger`
  survive a redesign; `grey_800` does not, and neither does anything named
  after where it happens to be used today.

Light and dark are two instances of the same `Palette`, so a widget written
against the tokens is automatically correct in both.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Palette:
    """One theme's colours."""

    #: Window and panel backgrounds, back to front.
    background: str
    surface: str
    surface_raised: str
    #: Inputs and lists, which sit *below* the surface rather than on it.
    field: str

    border: str
    border_strong: str
    #: The ring drawn around whatever has keyboard focus. Must be visible
    #: against both `surface` and `field`, or keyboard navigation is guesswork.
    focus: str

    text: str
    text_muted: str
    text_faint: str
    #: Text drawn on top of `accent`.
    on_accent: str

    accent: str
    accent_hover: str
    #: A wash of the accent, for selected rows and hover states.
    accent_soft: str

    success: str
    warning: str
    danger: str

    #: Drop shadow under floating panels, as an rgba() string.
    shadow: str
    #: Backdrop behind modal content and screen overlays.
    scrim: str


#: Deep indigo rather than neutral grey, so the interface belongs to the same
#: world as the character without being a costume.
DARK = Palette(
    background="#14161F",
    surface="#1B1E2A",
    surface_raised="#242838",
    field="#0F111A",
    border="#2E3346",
    border_strong="#3D445C",
    focus="#6FA8FF",
    text="#ECEFF6",
    text_muted="#A8AFC4",
    text_faint="#6E7690",
    on_accent="#10131C",
    accent="#F2C14E",
    accent_hover="#FFD167",
    accent_soft="#4A3F1E",
    success="#4FD08A",
    warning="#FFB43D",
    danger="#F0685A",
    shadow="rgba(0, 0, 0, 0.45)",
    scrim="rgba(8, 9, 14, 0.62)",
)

LIGHT = Palette(
    background="#F4F5F9",
    surface="#FFFFFF",
    surface_raised="#FFFFFF",
    field="#F0F1F6",
    border="#DCDFE9",
    border_strong="#C2C7D6",
    focus="#2E6FD9",
    text="#1B1E2A",
    text_muted="#5A6079",
    text_faint="#878DA3",
    on_accent="#2A1F00",
    accent="#B8860B",
    accent_hover="#A0740A",
    accent_soft="#F6E9C6",
    success="#1F8F5B",
    warning="#B26A00",
    danger="#C4362B",
    shadow="rgba(20, 22, 31, 0.16)",
    scrim="rgba(244, 245, 249, 0.72)",
)

@dataclass(frozen=True)
class Spacing:
    """A four-point scale. Anything between these values is a mistake."""

    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32


@dataclass(frozen=True)
class Radius:
    sm: int = 4
    md: int = 8
    lg: int = 12
    #: Panels that float free of any window chrome.
    panel: int = 14
    pill: int = 999


@dataclass(frozen=True)
class Type:
    """Segoe UI Variable is Windows 11's; Segoe UI is the Windows 10 fallback.

    Qt picks the first family it can resolve, so listing both costs nothing and
    means the interface looks native on either.
    """

    family: str = '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif'
    family_display: str = '"Segoe UI Variable Display", "Segoe UI", sans-serif'
    mono: str = '"Cascadia Code", "Consolas", "Courier New", monospace'

    caption: int = 11
    body: int = 13
    body_large: int = 14
    title: int = 17
    display: int = 22


@dataclass(frozen=True)
class Motion:
    """Durations in ms and easing curves.

    Short: the range where an animation reads as responsiveness rather than as
    something to wait for. Anything above ~250ms on a panel starts to feel like
    the app is slow, however pretty the curve is.
    """

    instant: int = 90
    quick: int = 150
    normal: int = 200
    slow: int = 250

    #: cubic-bezier control points, matching Windows 11's standard curves.
    ease_out: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    ease_in_out: tuple[float, float, float, float] = (0.6, 0.0, 0.4, 1.0)


SPACING = Spacing()
RADIUS = Radius()
TYPE = Type()
MOTION = Motion()


@dataclass(frozen=True)
class Theme:
    """A palette plus the scales, which is everything a widget needs."""

    palette: Palette
    dark: bool
    spacing: Spacing = SPACING
    radius: Radius = RADIUS
    type: Type = TYPE
    motion: Motion = MOTION

    def with_accent(self, accent: str, hover: str, soft: str, on_accent: str) -> Theme:
        """Re-theme around the user's Windows accent colour."""
        return replace(
            self,
            palette=replace(
                self.palette,
                accent=accent,
                accent_hover=hover,
                accent_soft=soft,
                on_accent=on_accent,
            ),
        )


DARK_THEME = Theme(palette=DARK, dark=True)
LIGHT_THEME = Theme(palette=LIGHT, dark=False)
