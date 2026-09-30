"""Runs the overlay: the scene, one surface per monitor, and the tutorial controls.

Everything that draws on screen for Claude goes through here, on the GUI
thread. The MCP tools that Claude calls run on the worker thread, so they talk
to this through queued Qt signals (see `tools.py`) and never touch a widget.

Two costs are kept at zero when there is nothing to show:

* no surfaces exist until the first annotation, and they hide when it goes;
* the expiry timer runs only while something can expire, and wakes once, at
  the next expiry, rather than polling.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..design.tokens import Theme
from .scene import DEFAULT_TTL, Highlight, Pointer, Scene, Step
from .surface import OverlaySurface


class TutorialControls(QWidget):
    """The one overlay window that *does* take clicks: Previous / Next / Close."""

    previous_requested = Signal()
    next_requested = Signal()
    close_requested = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._text = QLabel("", self)
        self._text.setWordWrap(True)
        self._text.setObjectName("title")
        self._progress = QLabel("", self)
        self._progress.setObjectName("caption")

        self._previous = QPushButton("Précédent", self)
        self._previous.clicked.connect(self.previous_requested.emit)
        self._next = QPushButton("Suivant", self)
        self._next.setDefault(True)
        self._next.clicked.connect(self.next_requested.emit)
        close = QPushButton("Fermer (Échap)", self)
        close.setObjectName("quiet")
        close.clicked.connect(self.close_requested.emit)

        buttons = QHBoxLayout()
        buttons.addWidget(self._progress)
        buttons.addStretch(1)
        buttons.addWidget(close)
        buttons.addWidget(self._previous)
        buttons.addWidget(self._next)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.addWidget(self._text)
        layout.addLayout(buttons)
        self.setFixedWidth(460)

    def show_step(self, text: str, progress: str, first: bool, last: bool) -> None:
        self._text.setText(text)
        self._progress.setText(progress)
        self._previous.setEnabled(not first)
        self._next.setText("Terminer" if last else "Suivant")
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()

    def _place(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:  # pragma: no cover
            return
        area = screen.availableGeometry()
        # Top centre: out of the way of whatever the steps point at, which
        # tends to be in the middle of the screen or near the taskbar.
        self.move(area.center().x() - self.width() // 2, area.top() + 24)


class OverlayManager(QObject):
    """Owns what is on screen for Claude, and clears it."""

    #: The overlay went from empty to showing something, or back.
    active_changed = Signal(bool)

    def __init__(
        self,
        theme: Theme,
        default_ttl: float = DEFAULT_TTL,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._ttl = default_ttl
        self._scene = Scene()
        self._surfaces: dict[str, OverlaySurface] = {}
        self._controls: TutorialControls | None = None
        self._active = False
        #: Called with True/False when Escape should or should not be grabbed.
        self.escape_hook: Callable[[bool], None] | None = None
        #: Called with each new surface, so captures can hide it. Surfaces
        #: are translucent, and Windows refuses to exclude translucent
        #: windows from capture, so hiding them is the only reliable way.
        self.surface_created: Callable[[QWidget], None] | None = None

        self._expiry = QTimer(self)
        self._expiry.setSingleShot(True)
        self._expiry.timeout.connect(self._on_expiry)
        self._elapsed_at_arm = 0.0
        self._armed_for = 0.0

    # -- settings ----------------------------------------------------------

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        for surface in self._surfaces.values():
            surface.set_theme(theme)

    @property
    def scene(self) -> Scene:
        return self._scene

    # -- what Claude asks for (already in logical coordinates) -------------

    def point_at(self, x: float, y: float, label: str = "") -> None:
        self._scene.replace([Pointer(x, y, label)], self._ttl)
        self._render()

    def highlight(
        self,
        left: float,
        top: float,
        width: float,
        height: float,
        label: str = "",
        shape: str = "rect",
    ) -> None:
        box = Highlight(left, top, width, height, label, shape)
        self._scene.replace([box], self._ttl)
        self._render()

    def show_steps(self, steps: list[Step]) -> None:
        self._scene.start_tutorial(steps)
        self._render()

    def clear(self) -> None:
        self._scene.clear()
        self._render()

    # -- tutorial navigation ----------------------------------------------

    def next_step(self) -> None:
        if self._scene.is_last_step:
            self.clear()
            return
        self._scene.next_step()
        self._render()

    def previous_step(self) -> None:
        self._scene.previous_step()
        self._render()

    # -- rendering ---------------------------------------------------------

    def _render(self) -> None:
        items = self._scene.visible_items()
        step = None
        if self._scene.in_tutorial:
            step = (self._scene.step_index + 1, len(self._scene.steps))

        if items:
            for screen in QGuiApplication.screens():
                self._surface_for(screen).set_items(items, step)
        for surface in self._surfaces.values():
            if not items:
                surface.set_items([])

        self._update_controls()
        self._arm_expiry()
        self._set_active(not self._scene.empty)

    def _surface_for(self, screen) -> OverlaySurface:
        key = screen.name() or str(id(screen))
        surface = self._surfaces.get(key)
        if surface is None:
            surface = OverlaySurface(screen, self._theme)
            self._surfaces[key] = surface
            if self.surface_created is not None:
                self.surface_created(surface)
        return surface

    def _update_controls(self) -> None:
        if not self._scene.in_tutorial:
            if self._controls is not None:
                self._controls.hide()
            return
        if self._controls is None:
            self._controls = TutorialControls()
            self._controls.next_requested.connect(self.next_step)
            self._controls.previous_requested.connect(self.previous_step)
            self._controls.close_requested.connect(self.clear)
        step = self._scene.current_step
        self._controls.show_step(
            step.text if step else "",
            self._scene.progress(),
            first=self._scene.step_index == 0,
            last=self._scene.is_last_step,
        )

    # -- expiry, without polling ------------------------------------------

    def _arm_expiry(self) -> None:
        self._expiry.stop()
        wait = self._scene.next_expiry()
        if wait is None:
            return
        self._armed_for = wait
        # A few ms of slack so the annotation is past its time when we check.
        self._expiry.start(int(wait * 1000) + 30)

    def _on_expiry(self) -> None:
        self._scene.tick(self._armed_for + 0.03)
        self._render()

    def _set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if self.escape_hook is not None:
            self.escape_hook(active)
        self.active_changed.emit(active)

    @property
    def active(self) -> bool:
        return self._active
