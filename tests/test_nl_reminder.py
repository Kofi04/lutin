"""Reminders written the way people say them."""

from __future__ import annotations

from datetime import datetime

import pytest

from wizard.features.nl_reminder import parse_reminder

NOON = datetime(2026, 10, 1, 12, 0, 0)


@pytest.mark.parametrize(
    ("text", "seconds", "label"),
    [
        ("rappelle-moi dans 20 minutes d'appeler Koffi", 1200, "Appeler Koffi"),
        ("Rappelle moi dans 1h30 de relancer le client", 5400, "Relancer le client"),
        ("rappel dans 2 h réunion budget", 7200, "Réunion budget"),
        ("rappelle-moi dans une heure de sortir", 3600, "Sortir"),
        (
            "rappelle-moi dans un quart d'heure de vérifier le four",
            900,
            "Vérifier le four",
        ),
        ("rappelle-moi dans une demi-heure que le build tourne", 1800, "Le build tourne"),
        ("rappelle-moi dans 2 heures et demie d'appeler maman", 9000, "Appeler maman"),
        ("rappelle-moi dans 90 secondes du thé", 90, "Du thé"),
        ("rappelle-moi dans dix minutes de boire", 600, "Boire"),
        ("fais-moi penser dans 5 min à la lessive", 300, "À la lessive"),
    ],
)
def test_relative_delays(text, seconds, label):
    parsed = parse_reminder(text, NOON)

    assert parsed is not None
    assert parsed.seconds == seconds
    assert parsed.label == label


def test_the_time_can_come_at_the_end():
    parsed = parse_reminder("rappelle-moi d'arroser les plantes dans 45 minutes", NOON)

    assert (parsed.seconds, parsed.label) == (2700, "Arroser les plantes")


def test_a_clock_time_later_today():
    parsed = parse_reminder("rappel à 15h30 appeler la banque", NOON)

    assert parsed.seconds == 3 * 3600 + 1800
    assert parsed.label == "Appeler la banque"


def test_a_clock_time_already_past_means_tomorrow():
    parsed = parse_reminder("rappelle-moi à 9h de payer le loyer", NOON)

    assert parsed.seconds == 21 * 3600


def test_without_a_label_it_is_just_a_reminder():
    assert parse_reminder("rappelle-moi dans 10 minutes", NOON).label == "Rappel"


@pytest.mark.parametrize(
    "text",
    [
        "appelle Koffi dans 20 minutes",  # no trigger: not a reminder request
        "rappelle-moi d'appeler Koffi",  # no time: guessing one would be worse
        "rappel à 27h",  # not a time
        "rappelle-moi dans 400 heures",  # past a week: almost certainly a mistake
        "",
    ],
)
def test_what_is_not_a_reminder(text):
    assert parse_reminder(text, NOON) is None


def test_the_description_says_when():
    assert (
        parse_reminder("rappel dans 1h30 x", NOON).describe() == "Rappel dans 1 h 30 : X"
    )
    assert (
        parse_reminder("rappel dans 20 min x", NOON).describe()
        == "Rappel dans 20 min : X"
    )


def test_claude_can_set_a_reminder_through_its_tool():
    import asyncio

    from wizard.overlay.tools import OverlayBridge, build_handlers

    bridge = OverlayBridge()
    seen = []
    bridge.reminder_requested.connect(
        lambda seconds, label: seen.append((seconds, label))
    )
    handlers = build_handlers(bridge, lambda: None)

    result = asyncio.run(
        handlers["set_reminder"]({"minutes": 20, "label": "Appeler Koffi"})
    )

    # Works without any screen capture, and tells Claude it is volatile.
    assert seen == [(1200, "Appeler Koffi")]
    assert "perdu" in result["content"][0]["text"]


def test_the_reminder_tool_refuses_absurd_durations():
    import asyncio

    from wizard.overlay.tools import OverlayBridge, build_handlers

    handlers = build_handlers(OverlayBridge(), lambda: None)

    assert asyncio.run(handlers["set_reminder"]({"minutes": 99999}))["is_error"]
    assert asyncio.run(handlers["set_reminder"]({"minutes": "bientôt"}))["is_error"]
