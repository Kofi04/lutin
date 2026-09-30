"""Subsequence matching with scoring, for the command palette.

A palette lives or dies on its ranking. Typing "npr" should find *N*ote
*r*apide before it finds anything containing those three letters somewhere in
the middle, and typing nothing at all should leave the caller's own order
alone.

The rules, in order of weight:

* every character of the query must appear, in order (a subsequence match);
* a match at a word boundary beats one inside a word;
* consecutive matches beat scattered ones;
* an earlier match beats a later one;
* a short haystack beats a long one, so "Notes" wins over "Notes de réunion".

Accents are folded, because "reunion" must find "réunion" — on a French
interface, requiring the accent to search is the difference between a palette
you use and one you give up on.

Pure functions, no Qt: the ranking is the part worth testing, and it is tested
without a display.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

#: Points for a match that starts a word, or follows a separator.
_BOUNDARY_BONUS = 12.0
#: Points for a match immediately after the previous one. Deliberately worth
#: more than a word boundary: without that, "C L A U D E autre chose" scores
#: six boundary bonuses and beats "Demander à Claude", which is absurd.
_CONSECUTIVE_BONUS = 16.0
#: Points for matching the very first character.
_FIRST_CHAR_BONUS = 10.0
#: Penalty per character skipped before a match.
_GAP_PENALTY = 0.6
#: Penalty per character of haystack, to prefer the shorter of two matches.
_LENGTH_PENALTY = 0.12

_SEPARATORS = frozenset(" \t-_/\\.:,()[]{}'\"")


def fold(text: str) -> str:
    """Lowercase and strip accents, so "reunion" matches "Réunion"."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


@dataclass(frozen=True)
class Match:
    """A scored hit, with the positions that matched for highlighting."""

    score: float
    positions: tuple[int, ...]


def score(query: str, text: str) -> Match | None:
    """Score `query` against `text`, or None when it does not match at all."""
    if not query:
        return Match(0.0, ())
    if not text:
        return None

    needle = fold(query)
    haystack = fold(text)
    # Folding can change length (composed characters decompose), so positions
    # are reported against the folded string and used only for highlighting.
    if len(needle) > len(haystack):
        return None

    total = 0.0
    positions: list[int] = []
    cursor = 0
    previous = -2

    for char in needle:
        if char.isspace():
            # Spaces in a query mean "and then", not a literal space.
            continue
        found = haystack.find(char, cursor)
        if found < 0:
            return None

        if found == 0:
            total += _FIRST_CHAR_BONUS
        elif haystack[found - 1] in _SEPARATORS:
            total += _BOUNDARY_BONUS
        if found == previous + 1:
            total += _CONSECUTIVE_BONUS

        gap = found - cursor
        total -= gap * _GAP_PENALTY

        positions.append(found)
        previous = found
        cursor = found + 1

    total -= len(haystack) * _LENGTH_PENALTY
    # An exact prefix is what the user almost certainly meant.
    if haystack.startswith(needle):
        total += 25.0
    return Match(total, tuple(positions))


def rank(query: str, items, key=str, limit: int | None = None) -> list:
    """Filter and order `items` by how well they match `query`.

    With an empty query the caller's order is preserved, because that order is
    usually meaningful (most recent first, or hand-arranged).
    """
    if not query.strip():
        return list(items)[:limit] if limit else list(items)

    scored = []
    for index, item in enumerate(items):
        hit = score(query, key(item))
        if hit is not None:
            # The index keeps the sort stable for equal scores, which stops
            # results from shuffling as you type.
            scored.append((-hit.score, index, item))

    scored.sort(key=lambda row: (row[0], row[1]))
    ordered = [item for _, _, item in scored]
    return ordered[:limit] if limit else ordered
