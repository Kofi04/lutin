"""The design system: tokens, theme derivation, and the generated stylesheet."""

from __future__ import annotations

import dataclasses

import pytest
from PySide6.QtGui import QColor

from wizard.design import stylesheet
from wizard.design.theme import legible_fill, readable_on, theme_for
from wizard.design.tokens import (
    DARK,
    DARK_THEME,
    LIGHT,
    LIGHT_THEME,
    MOTION,
    RADIUS,
    SPACING,
    Palette,
)


def colour_fields():
    return [
        field.name
        for field in dataclasses.fields(Palette)
        if not field.name.startswith("_")
    ]


# -- the palettes ----------------------------------------------------------


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_every_colour_is_a_colour(palette):
    for name in colour_fields():
        value = getattr(palette, name)
        if value.startswith("rgba"):
            continue
        assert QColor(value).isValid(), f"{name} = {value!r}"


def test_the_two_palettes_define_the_same_names():
    # A token present in one theme and missing from the other is a widget that
    # renders in only one of them.
    assert {f.name for f in dataclasses.fields(DARK)} == {
        f.name for f in dataclasses.fields(LIGHT)
    }


@pytest.mark.parametrize(
    ("palette", "dark"), [(DARK, True), (LIGHT, False)], ids=["dark", "light"]
)
def test_body_text_is_readable_on_the_surface(palette, dark):
    # The one contrast failure that makes an app unusable rather than ugly.
    assert _contrast(palette.text, palette.surface) >= 4.5


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_muted_text_still_clears_the_large_text_bar(palette):
    assert _contrast(palette.text_muted, palette.surface) >= 3.0


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_accent_text_is_readable_on_the_accent(palette):
    assert _contrast(palette.on_accent, palette.accent) >= 4.5


@pytest.mark.parametrize("palette", [DARK, LIGHT], ids=["dark", "light"])
def test_the_focus_ring_is_visible_against_both_backgrounds(palette):
    # Keyboard navigation is guesswork without this.
    assert _contrast(palette.focus, palette.surface) >= 3.0
    assert _contrast(palette.focus, palette.field) >= 3.0


def test_dark_is_dark_and_light_is_light():
    assert _luminance(DARK.surface) < 0.2
    assert _luminance(LIGHT.surface) > 0.8


# -- readable_on -----------------------------------------------------------


@pytest.mark.parametrize(
    ("colour", "expect_dark_text"),
    [
        ("#FFFFFF", True),
        ("#FFFF00", True),
        ("#F2C14E", True),
        ("#000000", False),
        ("#2E6FD9", False),
        ("#7A1B1B", False),
    ],
)
def test_readable_on_picks_the_legible_side(colour, expect_dark_text):
    # An accent is whatever the user picked, and some of those are pale yellow.
    chosen = readable_on(colour)
    assert (_luminance(chosen) < 0.5) is expect_dark_text
    assert _contrast(chosen, colour) >= 4.5


# -- theme derivation ------------------------------------------------------


def test_no_accent_leaves_the_theme_alone():
    assert theme_for(True, None) == DARK_THEME
    assert theme_for(False, None) == LIGHT_THEME


def test_an_invalid_accent_is_ignored_rather_than_crashing():
    assert theme_for(True, "not a colour") == DARK_THEME


@pytest.mark.parametrize("dark", [True, False], ids=["dark", "light"])
@pytest.mark.parametrize("accent", ["#0078D7", "#FFFF00", "#101010", "#E81123"])
def test_a_system_accent_stays_readable(dark, accent):
    theme = theme_for(dark, accent)

    assert _contrast(theme.palette.on_accent, theme.palette.accent) >= 4.5
    # Still recognisably the colour the user chose.
    assert _hue_distance(theme.palette.accent, accent) <= 12


@pytest.mark.parametrize("dark", [True, False], ids=["dark", "light"])
def test_the_accent_wash_stays_close_to_the_surface(dark):
    # accent_soft is a hover/selection background: if it landed near the full
    # accent, every hover would shout.
    theme = theme_for(dark, "#E81123")

    assert _contrast(theme.palette.text, theme.palette.accent_soft) >= 3.5


# -- the stylesheet --------------------------------------------------------


@pytest.mark.parametrize("dark", [True, False], ids=["dark", "light"])
def test_the_stylesheet_renders_completely(dark):
    css = stylesheet(theme_for(dark, "#0078D7"))

    # An f-string that failed to interpolate leaves these behind.
    assert "None" not in css
    assert "{p." not in css
    assert "{s." not in css
    assert css.count("{") == css.count("}")


def test_the_stylesheet_uses_the_palette_it_was_given():
    css = stylesheet(theme_for(True, "#E81123"))

    assert "#e81123" in css.lower()
    assert DARK.field in css


def test_the_two_themes_produce_different_stylesheets():
    assert stylesheet(LIGHT_THEME) != stylesheet(DARK_THEME)


# -- the scales ------------------------------------------------------------


def test_spacing_is_a_rising_scale():
    values = [SPACING.xs, SPACING.sm, SPACING.md, SPACING.lg, SPACING.xl, SPACING.xxl]
    assert values == sorted(values)
    assert all(value % 4 == 0 for value in values)


def test_radii_rise():
    assert RADIUS.sm < RADIUS.md < RADIUS.lg <= RADIUS.panel < RADIUS.pill


def test_durations_are_short_enough_to_feel_responsive():
    # Past a quarter second a panel animation reads as the app being slow.
    for duration in (MOTION.instant, MOTION.quick, MOTION.normal, MOTION.slow):
        assert 50 <= duration <= 250


# -- helpers ---------------------------------------------------------------


def _luminance(colour: str) -> float:
    rgb = QColor(colour)
    channels = []
    for value in (rgb.redF(), rgb.greenF(), rgb.blueF()):
        channels.append(
            value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _hue_distance(a: str, b: str) -> int:
    first, second = QColor(a).hue(), QColor(b).hue()
    if first < 0 or second < 0:  # greys have no hue
        return 0
    gap = abs(first - second)
    return min(gap, 360 - gap)


def _contrast(a: str, b: str) -> float:
    first, second = _luminance(a), _luminance(b)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


# -- legible_fill ----------------------------------------------------------


@pytest.mark.parametrize(
    "accent",
    ["#0078D7", "#FFFF00", "#808080", "#7F7FFF", "#00A000", "#C0C0C0", "#946A3F"],
)
def test_legible_fill_always_reaches_the_contrast_bar(accent):
    # Windows' own default blue tops out at 4.499 against white and worse
    # against black: no text passes AA on it untouched.
    fill = legible_fill(accent)

    assert _contrast(readable_on(fill), fill) >= 4.5


def test_legible_fill_leaves_a_colour_that_already_works_alone():
    assert legible_fill("#000000") == "#000000"
    assert legible_fill("#FFFFFF") == "#FFFFFF"


def test_the_windows_default_blue_is_nudged_not_replaced():
    fill = legible_fill("#0078D7")

    assert fill.lower() != "#0078d7"
    assert _hue_distance(fill, "#0078D7") <= 6
