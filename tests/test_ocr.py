"""Local OCR: line handling, and reading real rendered text end to end."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from wizard.assistant import ocr


def test_lines_are_joined_and_trimmed():
    assert ocr.join_lines(["  Bonjour ", "", "   ", "le monde"]) == "Bonjour\nle monde"


def test_small_captures_are_upscaled_before_reading():
    from PySide6.QtGui import QImage

    small = QImage(400, 60, QImage.Format.Format_RGB32)
    small.fill(0xFFFFFFFF)
    png = ocr.prepare_png(small)

    decoded = QImage.fromData(png)
    assert decoded.width() == 800


def test_large_captures_are_left_alone():
    from PySide6.QtGui import QImage

    big = QImage(ocr.UPSCALE_BELOW + 100, 50, QImage.Format.Format_RGB32)
    big.fill(0xFFFFFFFF)

    assert QImage.fromData(ocr.prepare_png(big)).width() == ocr.UPSCALE_BELOW + 100


_READ_REAL_TEXT = textwrap.dedent(
    """
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from wizard.assistant import ocr
    image = QImage(560, 70, QImage.Format.Format_RGB32)
    image.fill(QColor("#FFFFFF"))
    painter = QPainter(image)
    font = QFont("Segoe UI")
    font.setPointSizeF(10)
    painter.setFont(font)
    painter.setPen(QColor("#000000"))
    painter.drawText(QRect(10, 10, 540, 50), 0, "Le fichier réunion.txt est introuvable")
    painter.end()
    # Deliberately on the GUI thread: this is where it used to deadlock.
    print(ocr.recognize_png(ocr.prepare_png(image), "fr-FR"))
    """
)


@pytest.mark.skipif(not ocr.available(), reason="extra [ocr] not installed")
def test_real_text_is_read_with_its_accents():
    # The suite runs on the offscreen platform, which has no fonts; render on
    # the real one in a child process.
    result = subprocess.run(
        [sys.executable, "-c", _READ_REAL_TEXT],
        capture_output=True,
        timeout=60,
        env={
            **__import__("os").environ,
            "QT_QPA_PLATFORM": "windows",
            "PYTHONIOENCODING": "utf-8",
        },
    )
    text = result.stdout.decode("utf-8", errors="replace").strip()

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert "réunion" in text
    assert "introuvable" in text
