"""How a character gets drawn, and who gets to draw it.

Two implementations exist: `painter.PainterRenderer` draws the wizard with
QPainter, and `sheet.SheetRenderer` blits PNG frames from disk. `load_renderer`
picks the sheet when the files are there and falls back to the painter when they
are not, so the rest of the app never learns which one it got.

The protocol is deliberately tiny — one method — because every extra method is
something a future art pipeline would have to implement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from PySide6.QtGui import QPainter

from .animation import Frame

#: Design size. Every coordinate in a renderer is expressed against this square
#: and scaled at draw time, so the character is resolution-independent.
BASE_SIZE = 96


@runtime_checkable
class Renderer(Protocol):
    """Draws one frame into a size x size square at the painter's origin."""

    def draw(self, painter: QPainter, size: float, frame: Frame) -> None: ...

    @property
    def name(self) -> str:
        """Short identifier, so the app can say which source it is using."""
        ...


def assets_dir() -> Path:
    """Where hand-drawn frames go, if there are any."""
    return Path(__file__).resolve().parents[3] / "assets" / "character"


def load_renderer(directory: Path | None = None) -> Renderer:
    """The best renderer available: hand-drawn art if present, code if not."""
    from .painter import PainterRenderer
    from .sheet import SheetRenderer

    sheet = SheetRenderer.load(directory if directory is not None else assets_dir())
    return sheet if sheet is not None else PainterRenderer()
