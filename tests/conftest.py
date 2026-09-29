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
    """One QGuiApplication for the whole session; image codecs need it."""
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication([])
    yield app
