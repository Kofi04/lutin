"""The wizard's colours, in one place.

Indigo, ocre, terracotta and gold, with one luminous accent per pose — the
"magic" at the tip of his staff, which is also the app's state indicator. That
double duty is the point: you read what the app is doing from the one part of
the character that glows, not from a badge bolted onto him.

Kept apart from the drawing code so the sprite-sheet pipeline and the
`docs/ASSETS_BRIEF.md` character sheet can quote the same hex values, and so a
palette tweak is not a diff through 400 lines of geometry.
"""

from __future__ import annotations

from .emote import Emote

# -- the character ----------------------------------------------------------

INDIGO_DEEP = "#171B44"
INDIGO = "#2A3373"
INDIGO_LIT = "#3D4A9B"
OCRE = "#D9982F"
TERRACOTTA = "#B4543A"
GOLD = "#F2C14E"
CREAM = "#F6EFE0"

SKIN = "#7A4B2A"
SKIN_SHADOW = "#5C361D"
SKIN_LIT = "#8E5C36"

INK = "#191A22"

# -- the accent, which doubles as the app's state light ---------------------

#: Pose -> (glow core, glow halo). The core is what the staff tip is painted
#: with; the halo is the soft light around it.
ACCENT: dict[Emote, tuple[str, str]] = {
    Emote.IDLE: (GOLD, "#F2C14E"),
    Emote.BUSY: (OCRE, "#E8A93F"),
    Emote.STRESSED: ("#F0685A", "#E2574C"),
    Emote.TIRED: ("#9C8FD4", "#7B6BA8"),
    Emote.WORKING: ("#78C0F5", "#3E93DC"),
    Emote.THINKING: ("#8FE0EC", "#4FC3D6"),
    # Amber, and the brightest thing he ever does: this is the one state that
    # needs you to look up and answer.
    Emote.WAITING_APPROVAL: ("#FFC85C", "#FF9F1C"),
    Emote.SUCCESS: ("#74E3A8", "#34C77B"),
    Emote.CONFUSED: ("#F0685A", "#D6453A"),
    # Dim: a sleeping wizard should not light the room.
    Emote.SLEEPING: ("#5A5F86", "#3E4368"),
    Emote.GREETING: (GOLD, "#F2C14E"),
    Emote.LISTENING: ("#6FE3CE", "#2FBFA6"),
    Emote.SPEAKING: ("#9AD7F7", "#5AB0E8"),
    Emote.POINTING: ("#FFD97A", "#F2B138"),
}


def accent(emote: Emote) -> tuple[str, str]:
    """The glow for a pose. Missing entries are a bug, not a default."""
    return ACCENT[emote]
