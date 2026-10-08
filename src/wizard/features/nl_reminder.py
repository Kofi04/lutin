"""Reminders written the way people say them.

"rappelle-moi dans 20 minutes d'appeler Awa", "rappel à 15h30 réunion",
"rappelle-moi d'arroser les plantes dans une heure et demie".

Deliberately small: one relative delay ("dans …") or one clock time ("à …"),
in French, anywhere in the sentence, and the rest becomes the label. Anything
it does not recognise is not a reminder — the command palette then simply
offers nothing, which is better than guessing a time the user did not mean.

Reminders still live in memory, as before: they are lost if the app closes,
and everything that creates one says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..fuzzy import fold

_TRIGGER = re.compile(
    r"^\s*(?:rappelle[- ]?moi|rappel|fais[- ]?moi penser|pense a me rappeler)\b[\s,:]*",
    re.IGNORECASE,
)

_NUMBER_WORDS = {
    "un": 1,
    "une": 1,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "onze": 11,
    "douze": 12,
    "quinze": 15,
    "vingt": 20,
    "trente": 30,
    "quarante": 40,
    "cinquante": 50,
    "soixante": 60,
}

_UNITS = {
    "s": 1,
    "sec": 1,
    "seconde": 1,
    "secondes": 1,
    "min": 60,
    "mn": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "heure": 3600,
    "heures": 3600,
}

_NUMBER = r"(\d+|" + "|".join(_NUMBER_WORDS) + r")"
_UNIT = r"(secondes?|sec|s|minutes?|min|mn|heures?|h)"

#: "dans un quart d'heure", "dans une demi-heure"
_SPECIAL = re.compile(r"\bdans (?:un )?quart d'?heure\b|\bdans une demi[- ]heure\b")
#: "dans 1h30", "dans 1 h 30", "dans 2 heures et demie", "dans 20 minutes"
_RELATIVE = re.compile(
    rf"\bdans {_NUMBER}\s*{_UNIT}"
    r"(?:\s*(?:et\s+)?(\d+|demie?|quart)\s*(?:min(?:utes?)?)?)?\b"
)
#: "à 15h", "a 15h30", "à 15:30", "vers 9h"
_CLOCK = re.compile(r"\b(?:a|vers)\s+(\d{1,2})\s*(?:h|:)\s*(\d{2})?\b")

_LEADING_FILLERS = re.compile(r"^(?:de |d'|que |qu'|pour |:|,|-)\s*", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedReminder:
    seconds: int
    label: str

    def describe(self) -> str:
        minutes, seconds = divmod(self.seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            when = f"{hours} h {minutes:02d}" if minutes else f"{hours} h"
        elif minutes:
            when = f"{minutes} min"
        else:
            when = f"{seconds} s"
        return f"Rappel dans {when} : {self.label}"


def _number(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBER_WORDS[token]


def _relative_seconds(match: re.Match) -> int:
    amount = _number(match.group(1))
    unit = _UNITS[match.group(2)]
    extra = match.group(3)
    seconds = amount * unit
    if extra:
        if extra in ("demi", "demie"):
            seconds += unit // 2
        elif extra == "quart":
            seconds += unit // 4
        elif unit == 3600:
            # "1h30": the trailing number is minutes.
            seconds += int(extra) * 60
        elif unit == 60:
            seconds += int(extra)
    return seconds


def parse_reminder(text: str, now: datetime | None = None) -> ParsedReminder | None:
    """A reminder from a sentence, or None if this is not one."""
    trigger = _TRIGGER.match(fold(text))
    if trigger is None:
        return None

    # Work on folded text for matching, but cut the label from the original so
    # it keeps its accents and capitals.
    folded = fold(text)
    if len(folded) != len(text):
        # Folding changed the length (decomposed characters): fall back to the
        # folded text, which is still a readable label.
        text = folded
    body_start = trigger.end()
    body_folded = folded[body_start:]
    body = text[body_start:]

    seconds = None
    span = None
    special = _SPECIAL.search(body_folded)
    relative = _RELATIVE.search(body_folded)
    clock = _CLOCK.search(body_folded)
    if special:
        seconds = 900 if "quart" in special.group(0) else 1800
        span = special.span()
    elif relative:
        seconds = _relative_seconds(relative)
        span = relative.span()
    elif clock:
        hour, minute = int(clock.group(1)), int(clock.group(2) or 0)
        if hour > 23 or minute > 59:
            return None
        current = now or datetime.now()
        target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= current:
            target += timedelta(days=1)
        seconds = int((target - current).total_seconds())
        span = clock.span()

    if not seconds or seconds <= 0 or seconds > 7 * 24 * 3600:
        return None

    label = (body[: span[0]] + " " + body[span[1] :]).strip()
    label = " ".join(label.split())
    while True:
        cleaned = _LEADING_FILLERS.sub("", label)
        if cleaned == label:
            break
        label = cleaned
    label = label.rstrip(" .,;:!")
    return ParsedReminder(
        seconds=seconds, label=label[:1].upper() + label[1:] if label else "Rappel"
    )
