"""Keep our own windows out of our own screenshots.

The obvious tool for this is `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`,
and it does not work here. Measured on Windows 10 22H2: it succeeds on an
opaque window and **fails with error 8 on any layered window** — which is every
window with a translucent background, and so both the floating avatar and the
on-screen overlay. The avatar had been appearing in captures despite the
setting that was meant to prevent it.

So this does the thing that works everywhere: hide our windows, give Windows a
moment to repaint what was under them, grab, and put them back. The avatar
blinks out for about a tenth of a second; in exchange, a capture is guaranteed
clean on every version of Windows, whatever the window style.

The delay is not optional. Hiding a window does not repaint the screen
synchronously; grab too early and the capture contains the window you just
hid — which is exactly the bug the region selector's veil had, and the one the
window picker still had until this module replaced its immediate grab.
"""

from __future__ import annotations

import itertools
import logging
import weakref
from collections.abc import Callable

from PySide6.QtCore import QTimer

log = logging.getLogger(__name__)

#: Long enough for DWM to recompose after a hide on a loaded machine; short
#: enough that the avatar's absence is a flicker, not a disappearance.
REPAINT_DELAY_MS = 80

#: How long the UI has to say its windows are hidden. Past that, grabbing
#: would risk a capture with our own windows in it, so the grab is abandoned.
ACK_TIMEOUT_MS = 600


class Cloak:
    """Hides registered windows around a grab, then restores exactly those."""

    def __init__(self, delay_ms: int = REPAINT_DELAY_MS) -> None:
        self._delay = delay_ms
        # Weak, so registering a panel never keeps it alive after it closes.
        self._widgets: list[weakref.ref] = []
        self._busy = False

    def add(self, widget) -> None:
        if not any(ref() is widget for ref in self._widgets):
            self._widgets.append(weakref.ref(widget))

    @property
    def busy(self) -> bool:
        """True between hiding and restoring; a second grab must wait."""
        return self._busy

    def around(
        self, action: Callable[[], None], on_abort: Callable[[], None] | None = None
    ) -> bool:
        """Hide, wait, run `action`, restore. Returns False if already busy.

        Hiding a local window cannot fail, so `on_abort` is never called here;
        it is in the signature because `RemoteCloak` can abort.

        `action` runs after the delay, from the event loop. The windows come
        back even if it raises: a capture that fails must not leave the user
        with no avatar and no idea where it went.
        """
        if self._busy:
            return False
        self._busy = True
        hidden = []
        for ref in self._widgets:
            widget = ref()
            if widget is not None and widget.isVisible():
                widget.hide()
                hidden.append(widget)

        def run() -> None:
            try:
                action()
            finally:
                for widget in hidden:
                    widget.show()
                self._busy = False

        if self._delay <= 0:
            run()
        else:
            QTimer.singleShot(self._delay, run)
        return True


class RemoteCloak:
    """The same promise, for windows that belong to another process.

    The core cannot hide the Tauri windows itself. It asks every connected UI
    window to hide (`cloak.hide`), waits until each one has answered
    `cloak.ack`, gives the screen time to repaint, grabs, and sends
    `cloak.show`. A window that does not answer in time aborts the grab: a
    late capture is a nuisance, a capture with our own windows in it is the
    bug this module exists to prevent.
    """

    def __init__(
        self,
        broadcast: Callable[[str, dict], None],
        clients: Callable[[], list],
        delay_ms: int = REPAINT_DELAY_MS,
        ack_timeout_ms: int = ACK_TIMEOUT_MS,
    ) -> None:
        self._broadcast = broadcast
        self._clients = clients
        self._delay = delay_ms
        self._ids = itertools.count(1)
        self._current: str | None = None
        self._waiting: set = set()
        self._action: Callable[[], None] | None = None
        self._on_abort: Callable[[], None] | None = None
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(ack_timeout_ms)
        self._timer.timeout.connect(self._abort)

    @property
    def busy(self) -> bool:
        return self._current is not None

    def around(
        self, action: Callable[[], None], on_abort: Callable[[], None] | None = None
    ) -> bool:
        if self.busy:
            return False
        clients = list(self._clients())
        if not clients:
            # No UI connected: nothing of ours is on screen to hide.
            action()
            return True
        self._current = f"c{next(self._ids)}"
        self._waiting = set(clients)
        self._action = action
        self._on_abort = on_abort
        self._timer.start()
        self._broadcast("cloak.hide", {"cloak_id": self._current})
        return True

    def ack(self, client, cloak_id: str) -> None:
        """One UI window says it is hidden."""
        if cloak_id != self._current:
            return  # a late answer to an abandoned grab
        self._waiting.discard(client)
        self._maybe_ready()

    def forget(self, client) -> None:
        """A window that disconnected is not on screen any more."""
        if self.busy:
            self._waiting.discard(client)
            self._maybe_ready()

    def _maybe_ready(self) -> None:
        if self._waiting or not self._timer.isActive():
            return
        self._timer.stop()
        if self._delay <= 0:
            self._run()
        else:
            QTimer.singleShot(self._delay, self._run)

    def _run(self) -> None:
        cloak_id, action = self._current, self._action
        try:
            if action is not None:
                action()
        finally:
            self._finish(cloak_id)

    def _abort(self) -> None:
        # Name who did not answer: without it, "could not hide in time" says
        # nothing about which window to look at.
        late = sorted(getattr(c, "role", "?") or "?" for c in self._waiting)
        log.warning("cloak %s: no cloak.ack from %s", self._current, ", ".join(late))
        cloak_id, on_abort = self._current, self._on_abort
        self._finish(cloak_id)
        if on_abort is not None:
            on_abort()

    def _finish(self, cloak_id: str | None) -> None:
        self._current = None
        self._waiting = set()
        self._action = self._on_abort = None
        if cloak_id is not None:
            self._broadcast("cloak.show", {"cloak_id": cloak_id})
