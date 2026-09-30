"""Test setup: Qt must be able to construct images without a display.

Setting the platform to "offscreen" before any PySide6 import lets the capture
tests build and encode QImages on a machine with no screen (and in CI).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def qt_app():
    """One QApplication for the whole session.

    QApplication rather than QGuiApplication: the image codecs only need the
    latter, but any test that builds a widget — the palette, the dialogs —
    needs the former, and QApplication is a subclass, so nothing that worked
    before stops working.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
