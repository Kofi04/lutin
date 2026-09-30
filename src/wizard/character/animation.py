"""The animation engine: states, transitions, a timeline, and nothing from Qt.

This module is deliberately ignorant of how the character is drawn. It answers
one question — "given everything that has happened, what should frame N look
like?" — and hands back a `Frame`. A QPainter renderer and a sprite-sheet
renderer consume the same `Frame`.

Keeping Qt out buys two things. It is unit-testable without a display, which is
where the real bugs live (a pose that never reverts, a blink that stops
happening, a transition that divides by zero). And it makes the renderer
replaceable, which is the whole point of Phase 1.

Time is injected, never read: `advance(dt)` is the only clock. That is what lets
a test fast-forward eight seconds in one call.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace

from .emote import Emote, duration_of, is_one_shot

#: How long one pose takes to blend into the next. Long enough to read as a
#: movement, short enough that a mood change still feels immediate.
TRANSITION_S = 0.18

#: A blink lasts this long, and they happen this often (uniformly random).
BLINK_S = 0.16
BLINK_EVERY = (2.5, 6.5)

#: With nothing happening for this long, he nods off. Generous on purpose: an
#: avatar that falls asleep while you are reading the screen is a nuisance.
SLEEP_AFTER_S = 180.0


def ease_out_cubic(t: float) -> float:
    t = _clamp01(t)
    return 1.0 - (1.0 - t) ** 3


def ease_in_out(t: float) -> float:
    t = _clamp01(t)
    return t * t * (3.0 - 2.0 * t)


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


@dataclass(frozen=True)
class Frame:
    """Everything a renderer needs for one frame. No Qt types, on purpose."""

    emote: Emote = Emote.IDLE
    #: The pose being blended out of, and how far along (1.0 = done).
    previous: Emote | None = None
    blend: float = 1.0

    #: Seconds spent in the current pose. Drives that pose's own loop.
    time: float = 0.0
    #: Seconds since the animator started. Drives the breathing bob, which must
    #: not restart every time the mood changes.
    total_time: float = 0.0

    #: 0 = shut, 1 = wide.
    eye_open: float = 1.0
    #: Where he is looking, each axis in [-1, 1].
    look: tuple[float, float] = (0.0, 0.0)

    pressed: bool = False
    hovered: bool = False
    #: A file is hovering over him: he cups his hands to catch it.
    catching: bool = False

    #: Microphone level in [0, 1]. Drives the staff's pulse while LISTENING.
    level: float = 0.0
    #: Direction to point in, each axis in [-1, 1], when POINTING.
    aim: tuple[float, float] = (0.0, 0.0)

    #: Link to Claude: "ready", "connecting" or "offline". Drawn as a small
    #: mark on the staff rather than as a pose, because it is orthogonal to
    #: what he is doing: you can be busy and offline at the same time.
    connection: str = "ready"

    #: The contact shadow sells the float on the desktop. An app icon has
    #: nothing to float above, so the icon renderer turns it off.
    shadow: bool = True
    #: Enlarges the eyes and thickens the linework. At 16px the face is a
    #: handful of pixels and normal proportions turn to mush, so the icon
    #: renderer exaggerates them the way icon designers hint small sizes.
    feature_scale: float = 1.0

    def with_overrides(self, **changes: object) -> Frame:
        return replace(self, **changes)  # type: ignore[arg-type]


@dataclass
class Animator:
    """Drives one character. Feed it `advance(dt)`; read the `Frame` it returns."""

    base: Emote = Emote.IDLE
    #: Injected so blinking is deterministic under test.
    rng: random.Random = field(default_factory=random.Random)
    sleep_after: float = SLEEP_AFTER_S

    def __post_init__(self) -> None:
        self._current: Emote = self.base
        self._previous: Emote | None = None
        self._transition: float = 1.0
        self._pose_time: float = 0.0
        self._total: float = 0.0

        #: Set while a one-shot is playing; None the rest of the time.
        self._one_shot_left: float | None = None

        self._idle_for: float = 0.0
        self._asleep = False

        self._eye_open = 1.0
        self._blink_in = self._next_blink()
        self._blink_left = 0.0

        self._look = (0.0, 0.0)
        self._pressed = False
        self._hovered = False
        self._catching = False
        self._level = 0.0
        self._aim = (0.0, 0.0)
        self._connection = "ready"

    # -- inputs -----------------------------------------------------------

    def set_base(self, emote: Emote) -> None:
        """Set the resting pose, usually from the mood.

        A one-shot in flight is not interrupted: if he is mid-wave and the mood
        goes busy, he finishes the wave and lands on BUSY. Cutting an animation
        off halfway reads as a glitch, and the mood will still be there in two
        seconds.
        """
        if emote is self.base:
            return
        self.base = emote
        self._wake()
        if self._one_shot_left is None:
            self._switch_to(emote)

    def play(self, emote: Emote) -> None:
        """Play a pose now. One-shots revert on their own; states stay."""
        self._wake()
        self._switch_to(emote)
        self._one_shot_left = duration_of(emote) if is_one_shot(emote) else None

    def release(self) -> None:
        """Drop back to the resting pose, ending any pose `play()` started."""
        self._one_shot_left = None
        self._switch_to(self.base)

    def set_look(self, x: float, y: float) -> None:
        self._look = (_clamp(x, -1.0, 1.0), _clamp(y, -1.0, 1.0))

    def set_pressed(self, pressed: bool) -> None:
        self._pressed = pressed
        if pressed:
            self._wake()

    def set_hovered(self, hovered: bool) -> None:
        self._hovered = hovered
        if hovered:
            self._wake()

    def set_catching(self, catching: bool) -> None:
        self._catching = catching
        if catching:
            self._wake()

    def set_level(self, level: float) -> None:
        self._level = _clamp01(level)

    def set_aim(self, x: float, y: float) -> None:
        self._aim = (_clamp(x, -1.0, 1.0), _clamp(y, -1.0, 1.0))

    def set_connection(self, state: str) -> None:
        self._connection = state

    def notice_activity(self) -> None:
        """Something happened: reset the doze timer."""
        self._wake()

    # -- the clock --------------------------------------------------------

    def advance(self, dt: float) -> Frame:
        """Move time forward and return the frame to draw."""
        dt = max(0.0, dt)
        self._total += dt
        self._pose_time += dt

        if self._transition < 1.0:
            self._transition = _clamp01(self._transition + dt / TRANSITION_S)
            if self._transition >= 1.0:
                self._previous = None

        self._advance_one_shot(dt)
        self._advance_blink(dt)
        self._advance_doze(dt)

        return Frame(
            emote=self._current,
            previous=self._previous,
            blend=ease_out_cubic(self._transition),
            time=self._pose_time,
            total_time=self._total,
            eye_open=self._eye_open,
            look=self._look,
            pressed=self._pressed,
            hovered=self._hovered,
            catching=self._catching,
            level=self._level,
            aim=self._aim,
            connection=self._connection,
        )

    # -- internals --------------------------------------------------------

    def _switch_to(self, emote: Emote) -> None:
        if emote is self._current:
            return
        self._previous = self._current
        self._current = emote
        self._transition = 0.0
        self._pose_time = 0.0

    def _advance_one_shot(self, dt: float) -> None:
        if self._one_shot_left is None:
            return
        self._one_shot_left -= dt
        if self._one_shot_left <= 0.0:
            self._one_shot_left = None
            self._switch_to(self.base)

    def _next_blink(self) -> float:
        return self.rng.uniform(*BLINK_EVERY)

    def _advance_blink(self, dt: float) -> None:
        if self._asleep:
            # Eyes stay shut; no point scheduling blinks.
            self._eye_open = 0.0
            return

        if self._blink_left > 0.0:
            self._blink_left -= dt
            if self._blink_left <= 0.0:
                self._blink_left = 0.0
                self._eye_open = 1.0
                self._blink_in = self._next_blink()
            else:
                progress = 1.0 - self._blink_left / BLINK_S
                # One smooth down-and-up sweep across the blink.
                self._eye_open = abs(math.cos(progress * math.pi))
            return

        self._blink_in -= dt
        if self._blink_in <= 0.0:
            self._blink_left = BLINK_S
            self._eye_open = 1.0

    def _advance_doze(self, dt: float) -> None:
        if self.sleep_after <= 0.0:
            return
        # Only a genuinely idle wizard nods off. Anything Claude-driven, and any
        # pose the app asked for, counts as being awake.
        if self._current is not Emote.IDLE and not self._asleep:
            self._idle_for = 0.0
            return
        self._idle_for += dt
        if not self._asleep and self._idle_for >= self.sleep_after:
            self._asleep = True
            self._switch_to(Emote.SLEEPING)

    def _wake(self) -> None:
        self._idle_for = 0.0
        if self._asleep:
            self._asleep = False
            self._eye_open = 1.0
            self._blink_in = self._next_blink()
            self._switch_to(self.base)

    # -- introspection, for the tests and the tray ------------------------

    @property
    def current(self) -> Emote:
        return self._current

    @property
    def asleep(self) -> bool:
        return self._asleep

    @property
    def playing_one_shot(self) -> bool:
        return self._one_shot_left is not None


def still_frame(emote: Emote, **overrides: object) -> Frame:
    """One settled frame of a pose, for icons and for rendering a contact sheet."""
    frame = Frame(emote=emote, previous=None, blend=1.0)
    return frame.with_overrides(**overrides) if overrides else frame
