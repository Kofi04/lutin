"""Reading the text in a screen region, locally, with Windows' own OCR.

"Copy the text in this area" — an error dialog, a scanned PDF, a video frame —
without involving Claude at all: Windows.Media.Ocr runs on the machine, so
nothing leaves it, it is instant, and it costs nothing.

Requires the `[ocr]` extra (WinRT bindings). Without it, `available()` is
False and the feature says how to enable it instead of failing.

Two details matter for accuracy:

* **Small text is upscaled first.** Interface text at 100 % scaling is about
  12 px tall, below what the engine reads reliably; doubling a small capture
  recovers most of it. Large captures are left alone — the engine refuses
  anything over `OcrEngine.max_image_dimension`.
* **The language is chosen, not guessed.** The user's profile language first
  (French here), so accents come out right; English as the fallback.
"""

from __future__ import annotations

import asyncio
import threading

#: Below this width, double the image before reading it.
UPSCALE_BELOW = 1400


def available() -> bool:
    """Whether the [ocr] extra is installed — without touching WinRT.

    Only looks for the module. Importing WinRT on this thread would initialise
    COM here, and if that happens before Qt creates its QApplication, Qt's own
    COM initialisation conflicts with it and the process dies with an access
    violation (seen when this was called at test collection). Whether a
    language is actually installed is checked later, on the worker thread.
    """
    from importlib.util import find_spec

    try:
        return find_spec("winrt.windows.media.ocr") is not None
    except (ImportError, ValueError):
        return False


def languages() -> list[str]:
    """Installed OCR languages, read on a worker thread for the same reason."""
    if not available():
        return []
    found: list[str] = []

    def work() -> None:
        from winrt.windows.media.ocr import OcrEngine

        found.extend(
            lang.language_tag for lang in OcrEngine.available_recognizer_languages
        )

    worker = threading.Thread(target=work, name="wizard-ocr-languages", daemon=True)
    worker.start()
    worker.join(10)
    return found


def _engine(language: str | None):
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine

    if language:
        engine = OcrEngine.try_create_from_language(Language(language))
        if engine is not None:
            return engine
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("Aucune langue de reconnaissance de texte n'est installée.")
    return engine


async def _recognize_png(png: bytes, language: str | None) -> str:
    from winrt.windows.graphics.imaging import (
        BitmapDecoder,
        BitmapPixelFormat,
        SoftwareBitmap,
    )
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png)
    await writer.store_async()
    writer.detach_stream()
    stream.seek(0)

    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    # The engine wants BGRA8 or Gray8; a PNG may decode as something else.
    if bitmap.bitmap_pixel_format != BitmapPixelFormat.BGRA8:
        bitmap = SoftwareBitmap.convert(bitmap, BitmapPixelFormat.BGRA8)

    result = await _engine(language).recognize_async(bitmap)
    return join_lines([line.text for line in result.lines])


def join_lines(lines: list[str]) -> str:
    """One line per recognised line, blank ones dropped, edges trimmed."""
    return "\n".join(line.strip() for line in lines if line and line.strip())


def recognize_png(png: bytes, language: str | None = None, timeout: float = 15.0) -> str:
    """Read the text in a PNG. Blocking: tens to hundreds of ms.

    Always runs the WinRT calls on a fresh thread of its own. Called on the
    GUI thread, they deadlock: Qt initialises that thread as a COM
    single-threaded apartment, WinRT delivers async completions there as
    window messages, and asyncio.run never pumps them — the first attempt
    at this hung indefinitely. A worker thread gets a multi-threaded
    apartment and completes normally. Callers should still keep this off
    the GUI thread, but a mistake now costs a pause, not a frozen app.
    """
    if not available():
        raise RuntimeError(
            "La reconnaissance de texte n'est pas installée. Ajoutez l'extra : "
            'pip install -e ".[ocr]"'
        )
    outcome: dict = {}

    def work() -> None:
        try:
            outcome["text"] = asyncio.run(_recognize_png(png, language))
        except Exception as exc:  # WinRT raises OSError and friends
            outcome["error"] = exc

    worker = threading.Thread(target=work, name="wizard-ocr", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise RuntimeError("La reconnaissance de texte ne répond pas.")
    if "error" in outcome:
        raise RuntimeError(f"Reconnaissance impossible : {outcome['error']}")
    return outcome["text"]


def prepare_png(image) -> bytes:
    """A QImage as PNG, upscaled when the text is probably too small to read."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt

    if image.width() < UPSCALE_BELOW:
        image = image.scaled(
            image.width() * 2,
            image.height() * 2,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    buffer = QBuffer()
    buffer.setData(QByteArray())
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())
