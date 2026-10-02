"""Desktop coordinates <-> (screen, position on that screen).

Inside the core, a point is in Qt's logical desktop coordinates: one space
spanning every monitor. The Tauri UI draws in one window per monitor, so the
protocol speaks in `screen_id` plus logical pixels from that screen's top-left
corner, and each overlay window only has to apply its own scale factor.

`screen_id` is the Windows device name (`\\\\.\\DISPLAY1`), which Qt and Tauri
both report for the same monitor.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScreenArea:
    """One monitor, in logical desktop coordinates."""

    id: str
    left: float
    top: float
    width: float
    height: float

    def contains(self, x: float, y: float) -> bool:
        return (
            self.left <= x < self.left + self.width
            and self.top <= y < self.top + self.height
        )

    def distance_to(self, x: float, y: float) -> float:
        dx = max(self.left - x, 0.0, x - (self.left + self.width))
        dy = max(self.top - y, 0.0, y - (self.top + self.height))
        return (dx * dx + dy * dy) ** 0.5


def to_screen(x: float, y: float, screens: list[ScreenArea]) -> tuple[str, float, float]:
    """The screen a desktop point is on, and the point relative to it.

    A point between monitors (a gap in an irregular layout, or a coordinate
    Claude got slightly wrong) goes to the nearest one rather than nowhere.
    """
    if not screens:
        raise ValueError("no screen to place the point on")
    screen = next((s for s in screens if s.contains(x, y)), None)
    if screen is None:
        screen = min(screens, key=lambda s: s.distance_to(x, y))
    return screen.id, x - screen.left, y - screen.top


def from_screen(
    screen_id: str, x: float, y: float, screens: list[ScreenArea]
) -> tuple[float, float]:
    """The desktop point for a position on one screen."""
    for screen in screens:
        if screen.id == screen_id:
            return screen.left + x, screen.top + y
    raise ValueError(f"unknown screen: {screen_id!r}")


def current_screens() -> list[ScreenArea]:
    """The monitors as Qt sees them right now."""
    from PySide6.QtGui import QGuiApplication

    areas = []
    for screen in QGuiApplication.screens():
        geometry = screen.geometry()
        areas.append(
            ScreenArea(
                screen.name(),
                geometry.x(),
                geometry.y(),
                geometry.width(),
                geometry.height(),
            )
        )
    return areas
