"""System monitoring, mapped onto the avatar's mood.

The mood decision is a pure function (`mood_for`) kept separate from the Qt
timer that drives it, so it can be unit-tested without spinning up a
QApplication.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from .. import winapi
from ..config import MonitorSettings
from ..mood import Mood


@dataclass(frozen=True)
class Sample:
    cpu: float
    ram: float
    battery_percent: int | None
    on_ac: bool

    def summary(self) -> str:
        # French typography puts a non-breaking space before the percent sign.
        parts = [f"Processeur {self.cpu:.0f} %", f"Mémoire {self.ram:.0f} %"]
        if self.battery_percent is not None:
            suffix = " (en charge)" if self.on_ac else ""
            parts.append(f"Batterie {self.battery_percent} %{suffix}")
        return "   ·   ".join(parts)


def mood_for(sample: Sample, settings: MonitorSettings) -> Mood:
    """Pick a mood from one sample.

    Order matters: a machine that is both hammered and low on battery should
    read as stressed, since that is the more actionable signal.
    """
    if sample.cpu >= settings.cpu_stressed or sample.ram >= settings.ram_stressed:
        return Mood.STRESSED
    if (
        sample.battery_percent is not None
        and not sample.on_ac
        and sample.battery_percent <= settings.battery_low
    ):
        return Mood.TIRED
    if sample.cpu >= settings.cpu_busy:
        return Mood.BUSY
    return Mood.CALM


class SystemMonitor(QObject):
    """Polls the system counters on a timer and reports mood changes."""

    sampled = Signal(object, object)  # (Sample, Mood)

    def __init__(self, settings: MonitorSettings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._cpu = winapi.CpuSampler()
        self._last_sample: Sample | None = None
        self._last_mood = Mood.CALM

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        # Prime the CPU baseline immediately so the first real sample is valid.
        self._cpu.sample()

    @property
    def last_sample(self) -> Sample | None:
        return self._last_sample

    @property
    def last_mood(self) -> Mood:
        return self._last_mood

    def start(self) -> None:
        if self._settings.enabled:
            self._timer.start(int(self._settings.interval_seconds * 1000))

    def stop(self) -> None:
        self._timer.stop()

    def apply_settings(self, settings: MonitorSettings) -> None:
        self._settings = settings
        self.stop()
        self.start()

    def _tick(self) -> None:
        battery = winapi.battery_state()
        sample = Sample(
            cpu=self._cpu.sample(),
            ram=winapi.memory_load_percent(),
            battery_percent=battery.percent,
            on_ac=battery.on_ac,
        )
        self._last_sample = sample
        self._last_mood = mood_for(sample, self._settings)
        self.sampled.emit(sample, self._last_mood)
