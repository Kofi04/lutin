"""Hiding our own windows for the instant of a screen grab.

This replaces SetWindowDisplayAffinity, which Windows refuses (error 8) on any
translucent window — so the tests pin down the property that matters: our
windows are gone during the grab and back afterwards, whatever happens.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget

from wizard.capture.cloak import Cloak


@pytest.fixture
def widgets():
    made = [QWidget(), QWidget()]
    for widget in made:
        widget.show()
    yield made
    for widget in made:
        widget.close()


def test_registered_windows_are_hidden_during_the_grab(widgets):
    cloak = Cloak(delay_ms=0)
    for widget in widgets:
        cloak.add(widget)
    seen = []

    cloak.around(lambda: seen.append([w.isVisible() for w in widgets]))

    assert seen == [[False, False]]


def test_they_come_back_afterwards(widgets):
    cloak = Cloak(delay_ms=0)
    for widget in widgets:
        cloak.add(widget)

    cloak.around(lambda: None)

    assert all(widget.isVisible() for widget in widgets)


def test_they_come_back_even_if_the_grab_fails(widgets):
    # A failed capture must not leave the user with no avatar and no idea
    # where it went.
    cloak = Cloak(delay_ms=0)
    cloak.add(widgets[0])

    def explode():
        raise RuntimeError("grab failed")

    with pytest.raises(RuntimeError):
        cloak.around(explode)

    assert widgets[0].isVisible()
    assert not cloak.busy


def test_a_window_the_user_had_hidden_stays_hidden(widgets):
    # Restoring "everything registered" would un-hide an avatar the user had
    # deliberately put away.
    cloak = Cloak(delay_ms=0)
    for widget in widgets:
        cloak.add(widget)
    widgets[1].hide()

    cloak.around(lambda: None)

    assert widgets[0].isVisible()
    assert not widgets[1].isVisible()


def test_registering_twice_is_harmless(widgets):
    cloak = Cloak(delay_ms=0)
    cloak.add(widgets[0])
    cloak.add(widgets[0])

    cloak.around(lambda: None)

    assert widgets[0].isVisible()


def test_a_closed_window_does_not_break_it():
    cloak = Cloak(delay_ms=0)
    widget = QWidget()
    cloak.add(widget)
    widget.deleteLater()
    del widget

    ran = []
    cloak.around(lambda: ran.append(True))

    assert ran == [True]


def test_with_a_delay_the_grab_waits(qt_app, widgets):
    from PySide6.QtCore import QEventLoop, QTimer

    cloak = Cloak(delay_ms=30)
    cloak.add(widgets[0])
    ran = []

    cloak.around(lambda: ran.append(widgets[0].isVisible()))
    # Nothing yet: the screen has not had its chance to repaint.
    assert ran == []
    assert cloak.busy

    loop = QEventLoop()
    QTimer.singleShot(120, loop.quit)
    loop.exec()

    assert ran == [False]
    assert widgets[0].isVisible()
    assert not cloak.busy


def test_a_second_grab_during_the_first_is_refused(widgets):
    cloak = Cloak(delay_ms=50)
    cloak.add(widgets[0])

    assert cloak.around(lambda: None) is True
    # Hiding again mid-grab would record the hidden state as "visible" and
    # never restore the window.
    assert cloak.around(lambda: None) is False
