"""Drawing the character from image files instead of from code.

Drop PNGs into `assets/character/` as `wizard_<emote>_<frame>.png` and they take
over from the QPainter renderer. Nothing else in the app changes: both sides
speak `Frame`.

Two choices worth explaining:

* **A partial set is allowed.** Only `idle` is required; any pose you have not
  drawn yet falls back to `idle`, and `missing` lists what is absent. Demanding
  all fourteen poses before showing any of them would mean you could not look at
  the first one you generated.
* **Sheets do not get the procedural contact shadow.** Whatever shadow the art
  has is the shadow, and adding an ellipse under a drawing that already has one
  looks like a mistake.

`docs/ASSETS_BRIEF.md` is the authority on file names, sizes and framing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap

from .animation import Frame
from .emote import Emote, is_one_shot

#: wizard_<emote>_<frame>.png — the frame number may be zero- or one-based, and
#: may be zero-padded; only the order matters.
_NAME = re.compile(r"^wizard_(?P<emote>[a-z_]+)_(?P<index>\d+)\.png$", re.IGNORECASE)

#: Optional manifest, for when the defaults are wrong.
MANIFEST_NAME = "wizard.json"

DEFAULT_FPS = 12.0

#: Without this pose there is nothing to fall back to, so the loader declines.
REQUIRED = Emote.IDLE


@dataclass
class Clip:
    """One pose's frames, in order."""

    frames: list[QPixmap] = field(default_factory=list)
    fps: float = DEFAULT_FPS
    loop: bool = True

    def at(self, seconds: float) -> QPixmap:
        """The frame to show, `seconds` into the pose."""
        if len(self.frames) == 1:
            return self.frames[0]
        index = int(max(0.0, seconds) * self.fps)
        if self.loop:
            return self.frames[index % len(self.frames)]
        return self.frames[min(index, len(self.frames) - 1)]


class SheetRenderer:
    """Blits pre-drawn frames. Built only by `load`, which may decline."""

    def __init__(self, clips: dict[Emote, Clip], missing: tuple[Emote, ...]) -> None:
        self._clips = clips
        self.missing = missing

    @property
    def name(self) -> str:
        return "sheet"

    # -- loading ----------------------------------------------------------

    @classmethod
    def load(cls, directory: Path) -> SheetRenderer | None:
        """Read a folder of frames, or return None if there is nothing usable."""
        if not directory.is_dir():
            return None

        by_emote: dict[Emote, list[tuple[int, Path]]] = {}
        for path in sorted(directory.iterdir()):
            match = _NAME.match(path.name)
            if match is None:
                continue
            emote = _emote_named(match.group("emote"))
            if emote is None:
                continue
            by_emote.setdefault(emote, []).append((int(match.group("index")), path))

        if REQUIRED not in by_emote:
            return None

        settings = _read_manifest(directory / MANIFEST_NAME)
        clips: dict[Emote, Clip] = {}
        for emote, entries in by_emote.items():
            frames = [pixmap for _, pixmap in _load_frames(entries)]
            if not frames:
                continue
            per_pose = settings.get(emote.value, {})
            clips[emote] = Clip(
                frames=frames,
                fps=float(per_pose.get("fps", settings.get("fps", DEFAULT_FPS))),
                loop=bool(per_pose.get("loop", not is_one_shot(emote))),
            )

        if REQUIRED not in clips:
            return None

        missing = tuple(emote for emote in Emote if emote not in clips)
        return cls(clips, missing)

    # -- drawing ----------------------------------------------------------

    def draw(self, painter: QPainter, size: float, frame: Frame) -> None:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        target = QRectF(0.0, 0.0, size, size)

        if frame.previous is not None and frame.blend < 1.0:
            painter.save()
            painter.setOpacity(1.0 - frame.blend)
            self._blit(painter, target, frame.previous, frame.time)
            painter.restore()
            painter.save()
            painter.setOpacity(frame.blend)
            self._blit(painter, target, frame.emote, frame.time)
            painter.restore()
            return

        self._blit(painter, target, frame.emote, frame.time)

    def _blit(
        self, painter: QPainter, target: QRectF, emote: Emote, seconds: float
    ) -> None:
        clip = self._clips.get(emote) or self._clips[REQUIRED]
        pixmap = clip.at(seconds)
        painter.drawPixmap(
            target,
            pixmap,
            QRectF(0.0, 0.0, float(pixmap.width()), float(pixmap.height())),
        )

    def has(self, emote: Emote) -> bool:
        return emote in self._clips


def _emote_named(text: str) -> Emote | None:
    try:
        return Emote(text.lower())
    except ValueError:
        return None


def _load_frames(entries: list[tuple[int, Path]]) -> list[tuple[int, QPixmap]]:
    loaded: list[tuple[int, QPixmap]] = []
    for index, path in sorted(entries):
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            loaded.append((index, pixmap))
    return loaded


def _read_manifest(path: Path) -> dict:
    """Optional tuning. A broken manifest is ignored, never fatal."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def scaled_into(pixmap: QPixmap, side: int) -> QPixmap:
    """Helper for the icon renderer: fit a frame into a square."""
    return pixmap.scaled(
        side,
        side,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
