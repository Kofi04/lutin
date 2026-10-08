"""Everything the app shows, behind one interface.

The app decides *what* to show (a mood, an approval, a capture to confirm);
a presenter decides *how*. There is one: `ProtocolPresenter`
(presenter_remote.py), events over a local WebSocket to the Tauri UI. The
Qt widgets that were the other one went in phase M7; the interface stays,
so the app's tests can stand in a presenter of their own.

The app never touches a widget directly. When a presenter needs an answer
(an approval, a confirmed capture, a chosen action), it calls the app back:
`_on_approval_decided`, `_on_capture_confirmed`, `_on_selection_action`...
Nothing here blocks waiting for the user.
"""

from __future__ import annotations

#: The windows the app may ask for: a `window.open` event, which the Tauri UI
#: turns into a view of its app window (or the panel's palette).
WINDOWS = (
    "quick_note",
    "clipboard",
    "notes",
    "reminder",
    "palette",
    "settings",
    "history",
    "agent",
    "hooks.install",
    "hooks.uninstall",
    "onboarding",
)


class Presenter:
    """The interface. Every method is a no-op unless a presenter overrides it."""

    app = None

    # -- lifecycle --------------------------------------------------------

    def make_cloak(self):
        """The cloak captures must go through, or None for the default one."""
        return None

    def bind(self, app) -> None:
        """Called once the app's core objects exist."""
        self.app = app

    def report_already_running(self) -> int:
        """Another instance holds the lock. Returns the exit code."""
        return 0

    def preflight(self) -> int | None:
        """Last checks before starting; an exit code stops the start."""
        return None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def apply_config(self, config) -> None:
        pass

    # -- status -----------------------------------------------------------

    def notify(self, title: str, body: str, kind: str) -> None:
        pass

    def set_mood(self, mood) -> None:
        pass

    def set_connection(self, state: str, detail: str) -> None:
        pass

    def update_system(self, sample, mood) -> None:
        pass

    def set_quiet(self, quiet: bool) -> None:
        pass

    def toggle_avatar(self) -> None:
        pass

    def snap_avatar(self) -> None:
        pass

    def set_flags(
        self,
        autostart: bool | None = None,
        hooks_installed: bool | None = None,
        hooks_stale: bool | None = None,
    ) -> None:
        """Checkable entries of the tray menu."""

    # -- the panel --------------------------------------------------------

    def open_ask(
        self, capture=None, context: str | None = None, status: str = ""
    ) -> None:
        pass

    def reset_conversation(self) -> None:
        pass

    def answer_started(self) -> None:
        pass

    def answer_chunk(self, text: str) -> None:
        pass

    def answer_status(self, text: str) -> None:
        pass

    def answer_reset(self) -> None:
        pass

    def answer_finished(self, status: str) -> None:
        pass

    def answer_failed(self, message: str) -> None:
        pass

    # -- approvals, captures, selections ----------------------------------

    def ask_approval(self, request, timeout_seconds: int) -> None:
        """Show one request; the decision goes to app._on_approval_decided."""

    def select_region(self, mode: str) -> None:
        """Let the user draw a rectangle; mode is "ask" or "text"."""

    def preview_capture(self, capture) -> None:
        """Show what would be sent; confirmation goes to app._on_capture_confirmed."""

    def choose_selection_action(self, text: str) -> None:
        """Offer the actions; the choice goes to app._on_selection_action."""

    def selection_started(self, chosen, text: str) -> None:
        pass

    def selection_done(self, text: str) -> None:
        pass

    def selection_failed(self, message: str) -> None:
        pass

    def update_sessions(self, sessions: list) -> None:
        pass

    # -- the guide --------------------------------------------------------

    def guide_point(self, x: float, y: float, label: str) -> None:
        pass

    def guide_highlight(
        self, left: float, top: float, width: float, height: float, label: str, shape: str
    ) -> None:
        pass

    def guide_steps(self, steps: list) -> None:
        pass

    def guide_clear(self) -> None:
        pass

    # -- windows not ported yet -------------------------------------------

    def open_window(self, name: str) -> None:
        pass

    def confirm_hooks(self, plan, installing: bool) -> bool:
        """The exact change to settings.json, shown before it is made."""
        return False

    def show_onboarding(self) -> None:
        pass

    def on_escape(self) -> None:
        """Escape while the core holds it (a selection or the guide on screen)."""
        self.guide_clear()
