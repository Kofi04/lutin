"""Render every pose to one PNG, so the character can be judged by looking.

    .venv\\Scripts\\python.exe tools\\contact_sheet.py

Writes `docs/poses.png`: each pose at three sizes — 96px (how he appears on the
desktop), 48px (the smallest size the brief asks him to read at) and 16px (the
tray). Animated poses are sampled at a few points in their loop, because a pose
that looks fine frozen can still look wrong in motion.

Pass `--assets` to render from `assets/character/` instead of from QPainter.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from wizard.character.animation import Animator, still_frame  # noqa: E402
from wizard.character.emote import Emote  # noqa: E402
from wizard.character.painter import PainterRenderer  # noqa: E402
from wizard.character.renderer import load_renderer  # noqa: E402

#: Seconds into each pose to sample, so a loop is visible rather than guessed.
SAMPLES = (0.0, 0.35, 0.75)

CELL = 104
LABEL_W = 150
SMALL_W = 130
PAD = 10
BACKGROUND = QColor("#101218")


def render(
    renderer, emote: Emote, side: int, seconds: float, scale: float = 1.0
) -> QImage:
    image = QImage(side, side, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    frame = still_frame(emote, feature_scale=scale).with_overrides(
        time=seconds, total_time=seconds
    )
    renderer.draw(painter, float(side), frame)
    painter.end()
    return image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", action="store_true", help="render from assets/")
    parser.add_argument("--out", default=str(ROOT / "docs" / "poses.png"))
    args = parser.parse_args()

    app = QApplication([])  # noqa: F841 - QPixmap needs a live application
    renderer = load_renderer() if args.assets else PainterRenderer()
    print(f"renderer: {renderer.name}")

    poses = list(Emote)
    width = LABEL_W + len(SAMPLES) * (CELL + PAD) + SMALL_W + PAD * 2
    height = PAD + len(poses) * (CELL + PAD)

    sheet = QImage(width, height, QImage.Format.Format_ARGB32)
    sheet.fill(BACKGROUND)
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    for row, emote in enumerate(poses):
        top = PAD + row * (CELL + PAD)

        painter.setPen(QColor("#E6EDF3"))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(PAD, top, LABEL_W - PAD * 2, CELL),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            emote.value,
        )

        for column, seconds in enumerate(SAMPLES):
            x = LABEL_W + column * (CELL + PAD)
            painter.drawImage(
                QPointF(x, top + (CELL - 96) / 2),
                render(renderer, emote, 96, seconds),
            )

        # 48px and 16px, on the same baseline, to check it survives shrinking.
        x = LABEL_W + len(SAMPLES) * (CELL + PAD) + PAD
        painter.drawImage(QPointF(x, top + 28), render(renderer, emote, 48, 0.2))
        painter.drawImage(
            QPointF(x + 60, top + 44), render(renderer, emote, 32, 0.2, 1.2)
        )
        painter.drawImage(
            QPointF(x + 100, top + 52), render(renderer, emote, 16, 0.2, 1.45)
        )

    painter.end()

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not sheet.save(str(out), "PNG"):
        raise SystemExit(f"could not write {out}")
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB, {width}x{height})")

    # A quick sanity check the eye cannot do: is anything being drawn at all?
    blank = [
        emote.value
        for emote in poses
        if _is_blank(render(renderer, emote, 96, 0.2))
    ]
    if blank:
        print(f"WARNING: nothing drawn for {blank}")
    else:
        print(f"all {len(poses)} poses drew something")

    animator = Animator()
    for emote in poses:
        animator.play(emote)
        animator.advance(0.1)
    print("animator accepted every pose")
    return 0


def _is_blank(image: QImage) -> bool:
    return not any(
        image.pixelColor(x, y).alpha() > 8
        for x in range(0, image.width(), 3)
        for y in range(0, image.height(), 3)
    )


if __name__ == "__main__":
    raise SystemExit(main())
