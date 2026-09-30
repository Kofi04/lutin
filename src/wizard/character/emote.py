"""What the wizard can be doing, as one closed vocabulary.

`Mood` (in `mood.py`) answers "what is going on?" — it is about the machine and
about Claude. `Emote` answers "what does he look like?". Keeping them apart
matters because they are not the same shape: several moods share one pose, and
several poses have no mood at all behind them (nobody's CPU load makes him wave
hello).

Everything that draws the character speaks `Emote` and nothing else. That is
what lets a folder of PNGs replace the QPainter code without either side
knowing.
"""

from __future__ import annotations

from enum import Enum

from ..mood import Mood


class Emote(Enum):
    """One pose, with its own little animation."""

    #: Resting. Breathing, blinking, an occasional flick of the staff.
    IDLE = "idle"
    #: The machine is working hard.
    BUSY = "busy"
    #: The machine is struggling.
    STRESSED = "stressed"
    #: Low battery.
    TIRED = "tired"
    #: A Claude session is running.
    WORKING = "working"
    #: Claude is reasoning: symbols turn above the hat.
    THINKING = "thinking"
    #: Claude needs an answer. He holds out a scroll.
    WAITING_APPROVAL = "waiting_approval"
    #: It worked.
    SUCCESS = "success"
    #: It failed, or he did not understand.
    CONFUSED = "confused"
    #: Nothing has happened for a long time.
    SLEEPING = "sleeping"
    #: Hello. Played once, at startup.
    GREETING = "greeting"
    #: Listening to the microphone, hand cupped to his ear.
    LISTENING = "listening"
    #: Talking, or streaming an answer.
    SPEAKING = "speaking"
    #: Pointing at something on screen with the staff.
    POINTING = "pointing"


#: Poses that play once and then hand control back to the resting pose. Anything
#: not in here is a state: it lasts until something changes it.
ONE_SHOT: dict[Emote, float] = {
    Emote.GREETING: 2.2,
    Emote.SUCCESS: 2.0,
}

#: Mood -> resting pose. Every Mood must appear here; the test enforces it, so
#: adding a mood cannot silently fall back to IDLE.
_FROM_MOOD: dict[Mood, Emote] = {
    Mood.CALM: Emote.IDLE,
    Mood.BUSY: Emote.BUSY,
    Mood.STRESSED: Emote.STRESSED,
    Mood.TIRED: Emote.TIRED,
    Mood.WORKING: Emote.WORKING,
    Mood.WAITING: Emote.WAITING_APPROVAL,
    Mood.DONE: Emote.SUCCESS,
    Mood.ERROR: Emote.CONFUSED,
}


def emote_for(mood: Mood) -> Emote:
    """The resting pose for a mood."""
    return _FROM_MOOD[mood]


def is_one_shot(emote: Emote) -> bool:
    return emote in ONE_SHOT


def duration_of(emote: Emote) -> float:
    """How long a one-shot pose lasts. Zero for states, which never end."""
    return ONE_SHOT.get(emote, 0.0)
