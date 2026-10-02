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


# -- RemoteCloak: the windows belong to the Tauri UI -------------------------


def _spin(ms: int) -> None:
    """Run the Qt event loop for a while, so timers can fire."""
    import time

    from PySide6.QtCore import QCoreApplication

    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        time.sleep(0.005)


class _Wire:
    """Stands in for the WebSocket: records what the cloak broadcasts."""

    def __init__(self, clients):
        self.clients = list(clients)
        self.sent = []

    def broadcast(self, type_, payload):
        self.sent.append((type_, payload["cloak_id"]))


def test_remote_grab_waits_for_every_window_to_ack():
    from wizard.capture.cloak import RemoteCloak

    wire = _Wire(["avatar", "panel"])
    cloak = RemoteCloak(wire.broadcast, lambda: wire.clients, delay_ms=0)
    grabbed = []

    assert cloak.around(lambda: grabbed.append(True))
    assert wire.sent == [("cloak.hide", "c1")]

    cloak.ack("avatar", "c1")
    assert grabbed == []  # the panel is still on screen
    cloak.ack("panel", "c1")

    assert grabbed == [True]
    assert wire.sent[-1] == ("cloak.show", "c1")
    assert not cloak.busy


def test_remote_grab_is_abandoned_without_an_ack():
    """A capture with our own windows in it is worse than no capture."""
    from wizard.capture.cloak import RemoteCloak

    wire = _Wire(["avatar"])
    cloak = RemoteCloak(wire.broadcast, lambda: wire.clients, ack_timeout_ms=30)
    grabbed, aborted = [], []

    cloak.around(lambda: grabbed.append(True), on_abort=lambda: aborted.append(True))
    _spin(120)

    assert grabbed == []
    assert aborted == [True]
    assert wire.sent == [("cloak.hide", "c1"), ("cloak.show", "c1")]
    # And a late ack for the abandoned grab changes nothing.
    cloak.ack("avatar", "c1")
    assert grabbed == []


def test_remote_grab_with_no_window_connected_grabs_at_once():
    from wizard.capture.cloak import RemoteCloak

    wire = _Wire([])
    cloak = RemoteCloak(wire.broadcast, lambda: wire.clients)
    grabbed = []

    cloak.around(lambda: grabbed.append(True))

    assert grabbed == [True]
    assert wire.sent == []


def test_a_window_that_disconnects_no_longer_holds_the_grab():
    from wizard.capture.cloak import RemoteCloak

    wire = _Wire(["avatar", "panel"])
    cloak = RemoteCloak(wire.broadcast, lambda: wire.clients, delay_ms=0)
    grabbed = []

    cloak.around(lambda: grabbed.append(True))
    cloak.ack("avatar", "c1")
    cloak.forget("panel")

    assert grabbed == [True]


def test_remote_grab_waits_for_the_repaint_after_the_acks():
    from wizard.capture.cloak import RemoteCloak

    wire = _Wire(["avatar"])
    cloak = RemoteCloak(wire.broadcast, lambda: wire.clients, delay_ms=40)
    grabbed = []

    cloak.around(lambda: grabbed.append(True))
    cloak.ack("avatar", "c1")
    assert grabbed == []
    _spin(150)
    assert grabbed == [True]


def test_one_remote_grab_at_a_time():
    from wizard.capture.cloak import RemoteCloak

    wire = _Wire(["avatar"])
    cloak = RemoteCloak(wire.broadcast, lambda: wire.clients)

    assert cloak.around(lambda: None)
    assert not cloak.around(lambda: None)
