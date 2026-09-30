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

import weakref
from collections.abc import Callable

from PySide6.QtCore import QTimer

#: Long enough for DWM to recompose after a hide on a loaded machine; short
#: enough that the avatar's absence is a flicker, not a disappearance.
REPAINT_DELAY_MS = 80


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

    def around(self, action: Callable[[], None]) -> bool:
        """Hide, wait, run `action`, restore. Returns False if already busy.

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
