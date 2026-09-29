"""What the avatar is feeling, and why.

Mood used to live in `features/monitor.py` because it only ever reflected CPU
and RAM. It now also reflects Claude: a session waiting on you outranks a busy
machine, because one needs an answer and the other is just weather.
"""

from __future__ import annotations

from enum import Enum


class Mood(Enum):
    # From the machine.
    CALM = "calm"
    BUSY = "busy"
    STRESSED = "stressed"
    TIRED = "tired"
    # From Claude.
    WORKING = "working"  # a session is running
    WAITING = "waiting"  # a session needs your answer
    DONE = "done"  # a session just finished
    ERROR = "error"  # a session failed


#: Moods that come from Claude rather than from the hardware.
CLAUDE_MOODS = (Mood.WORKING, Mood.WAITING, Mood.DONE, Mood.ERROR)

#: Highest first. A question that needs answering beats everything; a finished
#: session beats a busy fan.
_PRIORITY = (Mood.WAITING, Mood.ERROR, Mood.WORKING, Mood.DONE)


def combine(system: Mood, claude: Mood | None) -> Mood:
    """Pick the mood to show when the machine and Claude disagree."""
    if claude is None:
        return system
    if claude in _PRIORITY:
        return claude
    return system


def claude_mood_for(states: list[str]) -> Mood | None:
    """Reduce the states of every known session to one mood, or None if idle."""
    if not states:
        return None
    if "waiting" in states:
        return Mood.WAITING
    if "error" in states:
        return Mood.ERROR
    if "working" in states or "thinking" in states:
        return Mood.WORKING
    if "done" in states:
        return Mood.DONE
    return None
