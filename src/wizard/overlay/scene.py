"""What the overlay is currently showing, as plain data.

The overlay windows only draw; this decides *what* to draw: which annotations
exist, when each one expires, and where a step-by-step tutorial is up to. Kept
free of Qt so the rules — expiry, step navigation, clearing — are tested
without a screen.

Coordinates here are always logical desktop coordinates, already mapped from
Claude's image pixels by `mapping.py`. Nothing in this module ever sees an
image coordinate, which is what keeps the mapping in exactly one place.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

#: Default lifetime of an annotation, in seconds. Long enough to find it and
#: read its label; short enough that the screen does not stay cluttered if
#: nobody dismisses it.
DEFAULT_TTL = 12.0

_ids = itertools.count(1)


@dataclass(frozen=True)
class Pointer:
    """An arrow pointing at one spot, with an optional label."""

    x: float
    y: float
    label: str = ""


@dataclass(frozen=True)
class Highlight:
    """A spotlight on a rectangle; the rest of the screen dims slightly."""

    left: float
    top: float
    width: float
    height: float
    label: str = ""
    #: "rect" or "ellipse".
    shape: str = "rect"


@dataclass(frozen=True)
class Step:
    """One step of a tutorial: a place on screen and what to do there."""

    text: str
    target: Pointer | Highlight | None = None


@dataclass
class Annotation:
    """Something on screen, and when it goes away."""

    item: Pointer | Highlight
    #: Seconds since the scene started; None means "until cleared".
    expires_at: float | None
    id: int = field(default_factory=lambda: next(_ids))


@dataclass
class Scene:
    """Everything currently on the overlay."""

    annotations: list[Annotation] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    step_index: int = 0
    #: The scene's clock, advanced by `tick`. Injected time, as in the
    #: animation engine, so expiry is testable without sleeping.
    now: float = 0.0

    # -- adding -----------------------------------------------------------

    def add(self, item: Pointer | Highlight, ttl: float | None = DEFAULT_TTL) -> int:
        expires = None if ttl is None or ttl <= 0 else self.now + ttl
        annotation = Annotation(item=item, expires_at=expires)
        self.annotations.append(annotation)
        return annotation.id

    def replace(self, items: list[Pointer | Highlight], ttl: float | None = DEFAULT_TTL):
        """Show exactly these, removing whatever was there.

        What a new answer from Claude usually wants: a fresh pointer should not
        leave the previous one hanging around pointing at something stale.
        """
        self.annotations.clear()
        return [self.add(item, ttl) for item in items]

    # -- time -------------------------------------------------------------

    def tick(self, seconds: float) -> bool:
        """Advance the clock. Returns True if anything expired."""
        self.now += max(0.0, seconds)
        before = len(self.annotations)
        self.annotations = [
            annotation
            for annotation in self.annotations
            if annotation.expires_at is None or annotation.expires_at > self.now
        ]
        return len(self.annotations) != before

    def next_expiry(self) -> float | None:
        """Seconds until the next annotation expires, or None if none will."""
        pending = [
            annotation.expires_at - self.now
            for annotation in self.annotations
            if annotation.expires_at is not None
        ]
        return max(0.0, min(pending)) if pending else None

    # -- tutorials --------------------------------------------------------

    def start_tutorial(self, steps: list[Step]) -> None:
        """Begin a step-by-step walkthrough, replacing anything shown."""
        self.annotations.clear()
        self.steps = [step for step in steps if step.text.strip()]
        self.step_index = 0

    @property
    def in_tutorial(self) -> bool:
        return bool(self.steps)

    @property
    def current_step(self) -> Step | None:
        if not self.steps:
            return None
        return self.steps[self.step_index]

    def next_step(self) -> bool:
        """Move forward. Returns False at the last step (nothing changes)."""
        if self.step_index + 1 >= len(self.steps):
            return False
        self.step_index += 1
        return True

    def previous_step(self) -> bool:
        if self.step_index <= 0:
            return False
        self.step_index -= 1
        return True

    @property
    def is_last_step(self) -> bool:
        return bool(self.steps) and self.step_index == len(self.steps) - 1

    def progress(self) -> str:
        """"2 / 5", for the tutorial controls."""
        if not self.steps:
            return ""
        return f"{self.step_index + 1} / {len(self.steps)}"

    # -- clearing ---------------------------------------------------------

    def clear(self) -> None:
        self.annotations.clear()
        self.steps = []
        self.step_index = 0

    @property
    def empty(self) -> bool:
        return not self.annotations and not self.steps

    def visible_items(self) -> list[Pointer | Highlight]:
        """What to draw right now: the annotations, or the current step's target."""
        if self.steps:
            target = self.current_step.target if self.current_step else None
            return [target] if target is not None else []
        return [annotation.item for annotation in self.annotations]
