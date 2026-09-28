"""Render the avatar into a multi-resolution Windows .ico.

Run it whenever sprite.py changes:

    .venv\\Scripts\\python.exe tools\\make_icon.py

Qt can write a .ico, but only a single-size one, and Windows then scales that
down for the taskbar - which is exactly where a fuzzy icon is most visible. So
we let Qt render one crisp PNG per size and assemble the ICO container here.
The format is simple enough that struct + the stdlib beats adding Pillow.
"""

from __future__ import annotations

import os
import pathlib
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QBuffer, QByteArray, Qt  # noqa: E402
from PySide6.QtGui import QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lutin.features.monitor import Mood  # noqa: E402
from lutin.sprite import SpriteState, draw_avatar  # noqa: E402

# Every size Windows asks for: 16 in the taskbar and tray, 32 on the desktop,
# 48 in medium-icon views, 256 for the extra-large view and the file dialog.
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

# The character does not fill its 96x96 design square, which is right for a
# floating sprite and wasteful for an icon. Zoom so it reads at 16px.
ZOOM = 1.26


def _feature_scale(size: int) -> float:
    """How much to exaggerate the eyes and mouth at this size.

    Below ~32px the face is a handful of pixels and the default proportions
    turn to mush, so the features grow as the tile shrinks. Above that the
    icon matches the on-screen avatar exactly.
    """
    if size >= 32:
        return 1.0
    if size >= 24:
        return 1.2
    return 1.45


def render(size: int) -> QByteArray:
    """Render the avatar at `size` and return the PNG bytes."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    centre = size / 2
    painter.translate(centre, centre)
    painter.scale(ZOOM, ZOOM)
    # The body sits slightly above the square's centre, so recentre on it.
    painter.translate(-centre, -centre + size * 0.02)

    draw_avatar(
        painter,
        size,
        SpriteState(
            mood=Mood.CALM,
            time=0.0,
            shadow=False,
            feature_scale=_feature_scale(size),
        ),
    )
    painter.end()

    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    if not pixmap.save(buffer, "PNG"):
        raise SystemExit(f"could not encode the {size}px frame as PNG")
    return buffer.data()


def build_ico(frames: dict[int, QByteArray]) -> bytes:
    """Assemble PNG frames into an ICO container.

    Layout: a 6-byte ICONDIR, then one 16-byte ICONDIRENTRY per image, then the
    image payloads. Windows Vista and later accept PNG payloads at any size,
    which keeps the 256px frame small.
    """
    entries = sorted(frames.items())
    header = struct.pack("<HHH", 0, 1, len(entries))  # reserved, type=icon, count
    offset = len(header) + 16 * len(entries)

    directory = bytearray()
    payloads = bytearray()
    for size, png in entries:
        data = bytes(png)
        directory += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,  # 0 encodes 256
            size if size < 256 else 0,
            0,  # palette size: 0 for truecolour
            0,  # reserved
            1,  # colour planes
            32,  # bits per pixel
            len(data),
            offset,
        )
        payloads += data
        offset += len(data)

    return bytes(header + directory + payloads)


def main() -> int:
    app = QApplication(sys.argv)  # noqa: F841 - QPixmap needs a live application

    target = pathlib.Path(__file__).resolve().parent.parent / "src" / "lutin" / "app.ico"
    frames = {size: render(size) for size in SIZES}
    target.write_bytes(build_ico(frames))

    print(f"wrote {target} ({target.stat().st_size} bytes, {len(frames)} sizes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
