"""Countdown reminders (including a pomodoro preset).

Timers live in memory only: they are meant for "remind me in 20 minutes", not
for appointments, so surviving a restart would be more surprising than useful.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal


@dataclass
class Reminder:
    id: int
    label: str
    total_seconds: int
    remaining: int

    @property
    def remaining_text(self) -> str:
        minutes, seconds = divmod(max(0, self.remaining), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


class TimerManager(QObject):
    """Owns the active reminders and ticks them down once per second."""

    fired = Signal(object)  # Reminder
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ids = itertools.count(1)
        self._reminders: dict[int, Reminder] = {}

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)

    @property
    def active(self) -> list[Reminder]:
        return sorted(self._reminders.values(), key=lambda r: r.remaining)

    def add(self, label: str, seconds: int) -> Reminder:
        if seconds <= 0:
            raise ValueError("un rappel exige une durée positive")
        reminder = Reminder(
            id=next(self._ids),
            label=label.strip() or "Rappel",
            total_seconds=seconds,
            remaining=seconds,
        )
        self._reminders[reminder.id] = reminder
        if not self._tick.isActive():
            self._tick.start()
        self.changed.emit()
        return reminder

    def cancel(self, reminder_id: int) -> None:
        if self._reminders.pop(reminder_id, None) is not None:
            self._stop_if_idle()
            self.changed.emit()

    def cancel_all(self) -> None:
        if self._reminders:
            self._reminders.clear()
            self._stop_if_idle()
            self.changed.emit()

    def _stop_if_idle(self) -> None:
        if not self._reminders:
            self._tick.stop()

    def _on_tick(self) -> None:
        done: list[Reminder] = []
        for reminder in self._reminders.values():
            reminder.remaining -= 1
            if reminder.remaining <= 0:
                done.append(reminder)

        for reminder in done:
            self._reminders.pop(reminder.id, None)
            self.fired.emit(reminder)

        self._stop_if_idle()
        self.changed.emit()


def parse_duration(text: str) -> int:
    """Parse "25", "25m", "1h30", "90s" or "1:30" into seconds.

    Being generous here matters: this is typed into a tiny box in a hurry, and
    a bare number should mean minutes because that is what people expect from a
    reminder box.
    """
    raw = text.strip().lower().replace(" ", "")
    if not raw:
        raise ValueError("empty duration")

    if ":" in raw:
        chunks = raw.split(":")
        if len(chunks) > 3 or not all(c.isdigit() for c in chunks if c != ""):
            raise ValueError(f"bad duration: {text!r}")
        values = [int(c or 0) for c in chunks]
        while len(values) < 3:
            values.insert(0, 0)  # "25:00" means minutes:seconds
        hours, minutes, seconds = values
        total = hours * 3600 + minutes * 60 + seconds
    elif raw.isdigit():
        total = int(raw) * 60  # a bare number means minutes
    else:
        total = 0
        number = ""
        units = {"h": 3600, "m": 60, "s": 1}
        for char in raw:
            if char.isdigit():
                number += char
            elif char in units:
                if not number:
                    raise ValueError(f"bad duration: {text!r}")
                total += int(number) * units[char]
                number = ""
            else:
                raise ValueError(f"bad duration: {text!r}")
        if number:  # trailing digits after a unit, e.g. "1h30" -> 30 minutes
            total += int(number) * 60

    if total <= 0:
        raise ValueError(f"duration must be positive: {text!r}")
    return total
