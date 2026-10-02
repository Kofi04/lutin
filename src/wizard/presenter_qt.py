"""The Qt widgets, as one presenter: the app as it has always looked.

This is the code that used to sit in app.py, moved, not rewritten. It goes
away in phase M7 of the UI migration, when the Tauri UI has replaced every
window here.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QMenu, QMessageBox, QSystemTrayIcon

from . import winapi
from .assistant import selection as selection_actions
from .avatar_window import AvatarWindow
from .branding import APP_NAME
from .character.emote import Emote
from .design import ThemeWatcher, animate, stylesheet
from .overlay.manager import OverlayManager
from .presenter import Presenter
from .tray import TrayIcon
from .ui import HistoryPanel, QuickNoteDialog, ReminderDialog
from .ui_agent import AgentDialog
from .ui_capture import CapturePreview
from .ui_claude import ApprovalCard, AskPanel
from .ui_history import HistoryWindow
from .ui_hooks import HookDiffDialog
from .ui_onboarding import OnboardingDialog, mark_shown
from .ui_palette import CommandPalette
from .ui_selection import SelectionResult
from .ui_sessions import SessionDock
from .ui_settings import SettingsWindow
from .ui_toast import ToastManager


class QtPresenter(Presenter):
    """Avatar, tray, toasts, overlay and every dialog, as Qt widgets."""

    def bind(self, app) -> None:
        super().bind(app)
        config = app.config

        # The theme is applied to the QApplication, so every dialog inherits
        # it and none of them carry a stylesheet of their own any more.
        self.theme = ThemeWatcher()
        self.toasts = ToastManager(self.theme.theme)
        self.overlay = OverlayManager(
            self.theme.theme, default_ttl=config.ui.overlay_seconds
        )
        self._home_position = None
        self._hidden_for_quiet = False

        self._ask_panel: AskPanel | None = None
        self._approval: ApprovalCard | None = None
        self._capture_preview: CapturePreview | None = None
        self._selection_result: SelectionResult | None = None
        self._agent_dialog: AgentDialog | None = None
        self._hook_dialog: HookDiffDialog | None = None
        self._history_window: HistoryWindow | None = None
        self._palette: CommandPalette | None = None
        self._settings: SettingsWindow | None = None
        self._note_dialog: QuickNoteDialog | None = None
        self._history: HistoryPanel | None = None
        self._reminder_dialog: ReminderDialog | None = None

        self.theme.changed.connect(self._apply_theme)
        self._apply_theme(self.theme.theme)

        self.avatar = AvatarWindow(config.appearance)
        self.tray = TrayIcon(config, app.timers)
        # The avatar is always-on-top, so without this the window lookup would
        # only ever find the avatar itself.
        app.capture.ignore_window(self.avatar)
        # WDA_EXCLUDEFROMCAPTURE fails on translucent windows (error 8), so
        # the avatar is hidden for the instant of each grab instead.
        app.capture.hide_during_capture(self.avatar)
        self.toasts.set_anchor(self.avatar)
        self.dock = SessionDock(self.avatar)
        app.capture.hide_during_capture(self.dock)

        self._connect(app)

    def _connect(self, app) -> None:
        avatar, tray, capture = self.avatar, self.tray, app.capture

        avatar.clicked.connect(self._show_action_menu_at_avatar)
        avatar.context_menu_requested.connect(tray.popup_menu)
        avatar.targeting_started.connect(capture.start_targeting)
        avatar.targeting_moved.connect(capture.update_target)
        avatar.targeting_finished.connect(capture.finish_targeting)
        avatar.targeting_cancelled.connect(capture.cancel_targeting)
        avatar.files_dropped.connect(app._on_files_dropped)
        avatar.position_changed.connect(self.dock.reposition)
        avatar.visibility_changed.connect(
            lambda visible: self.dock.set_suppressed(not visible)
        )
        self.dock.clicked.connect(self._on_dock_clicked)

        self.overlay.escape_hook = app._grab_escape
        self.overlay.surface_created = capture.hide_during_capture
        self.overlay.active_changed.connect(self._on_overlay_active)

        tray.capture_region_requested.connect(lambda: app._start_region("ask"))
        tray.ask_claude_requested.connect(lambda: app._open_ask(None))
        tray.reset_claude_requested.connect(app._reset_claude)
        tray.agent_requested.connect(app._open_agent_dialog)
        tray.install_hooks_requested.connect(lambda: app._manage_hooks(True))
        tray.uninstall_hooks_requested.connect(lambda: app._manage_hooks(False))
        tray.quick_note_requested.connect(lambda: self.open_window("quick_note"))
        tray.clipboard_requested.connect(lambda: self.open_window("clipboard"))
        tray.notes_requested.connect(lambda: self.open_window("notes"))
        tray.reminder_requested.connect(lambda: self.open_window("reminder"))
        tray.launch_requested.connect(app._launch)
        tray.cancel_timer_requested.connect(app.timers.cancel)
        tray.toggle_avatar_requested.connect(app._toggle_avatar)
        tray.snap_requested.connect(avatar.snap_to_taskbar)
        tray.reset_position_requested.connect(avatar.forget_position)
        tray.clipboard_capture_toggled.connect(app.clipboard.set_enabled)
        tray.autostart_toggled.connect(app._set_autostart)
        tray.reload_config_requested.connect(app.reload_config)
        tray.settings_requested.connect(lambda: self.open_window("settings"))
        tray.history_requested.connect(lambda: self.open_window("history"))
        tray.open_config_folder_requested.connect(app._open_config_folder)
        tray.quit_requested.connect(app.shutdown)

    # -- lifecycle --------------------------------------------------------

    def report_already_running(self) -> int:
        QMessageBox.information(
            None,
            APP_NAME,
            f"{APP_NAME} est déjà lancé — cherchez-le dans la zone "
            "de notification, près de l'horloge.",
        )
        return 0

    def preflight(self) -> int | None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            QMessageBox.critical(
                None,
                APP_NAME,
                "Aucune zone de notification n'est disponible : le sorcier "
                "n'aurait pas de menu.",
            )
            return 1
        return None

    def start(self) -> None:
        self.tray.show()
        self.avatar.show()
        self.avatar.play_emote(Emote.GREETING)

    def stop(self) -> None:
        self.tray.hide()
        self.avatar.hide()

    def apply_config(self, config) -> None:
        self.avatar.apply_appearance(config.appearance)
        self._protect_all()
        self.tray.apply_config(config)

    def _apply_theme(self, theme) -> None:
        """Restyle everything at once, including windows already open."""
        self.app.qt.setStyleSheet(stylesheet(theme))
        self.toasts.set_theme(theme)
        self.overlay.set_theme(theme)
        if self._ask_panel is not None:
            self._ask_panel.set_dark(theme.dark)

    def _protect(self, widget) -> None:
        """Hide one of our panels from screen sharing, if the user wants that.

        Only for opaque windows. The avatar and the overlay are translucent,
        and Windows refuses SetWindowDisplayAffinity on those (error 8, on
        this machine); they are kept out of our own captures by the cloak
        instead, and cannot be hidden from anyone else's.
        """
        if widget is None:
            return
        winapi.exclude_from_capture(
            int(widget.winId()), self.app.config.ui.exclude_from_capture
        )

    def _protect_all(self) -> None:
        for widget in (
            self._ask_panel,
            self._approval,
            self._palette,
            self._settings,
            self._capture_preview,
        ):
            self._protect(widget)

    # -- status -----------------------------------------------------------

    def notify(self, title: str, body: str, kind: str) -> None:
        self.toasts.show(title, body, kind)

    def set_mood(self, mood) -> None:
        self.avatar.set_mood(mood)

    def set_connection(self, state: str, detail: str) -> None:
        self.avatar.set_connection(state)
        self.tray.set_connection(state, detail)

    def update_system(self, sample, mood) -> None:
        self.tray.update_status(sample, mood)

    def set_quiet(self, quiet: bool) -> None:
        if quiet:
            self._hidden_for_quiet = self.avatar.isVisible()
            self.avatar.hide()
            self.toasts.clear()
        elif self._hidden_for_quiet:
            # Only put him back if we were the ones who hid him: the user
            # may have hidden him deliberately before the game started.
            self._hidden_for_quiet = False
            self.avatar.show()

    def toggle_avatar(self) -> None:
        visible = not self.avatar.isVisible()
        self.avatar.setVisible(visible)
        self.tray.set_avatar_visible(visible)

    def snap_avatar(self) -> None:
        self.avatar.snap_to_taskbar()

    def set_flags(
        self,
        autostart: bool | None = None,
        hooks_installed: bool | None = None,
        hooks_stale: bool | None = None,
    ) -> None:
        if autostart is not None:
            self.tray.set_autostart(autostart)
        if hooks_installed is not None:
            if hooks_stale is None:
                self.tray.set_hooks_installed(hooks_installed)
            else:
                self.tray.set_hooks_installed(hooks_installed, hooks_stale)

    def _show_action_menu_at_avatar(self) -> None:
        # Anchor the menu to the avatar's top-left so it opens over the desktop
        # rather than off the bottom of the screen.
        self.tray.popup_menu(self.avatar.mapToGlobal(self.avatar.rect().topLeft()))

    # -- the panel --------------------------------------------------------

    def open_ask(
        self, capture=None, context: str | None = None, status: str = ""
    ) -> None:
        if self._ask_panel is None:
            self._ask_panel = AskPanel()
            self._protect(self._ask_panel)
            self._ask_panel.set_dark(self.theme.theme.dark)
            self._ask_panel.asked.connect(self.app._on_asked)
            self._ask_panel.interrupted.connect(self.app.claude.cancel)
        self._ask_panel.open_with(capture)
        if context is not None:
            self._ask_panel.reset_answer()
            self._ask_panel.set_context(context)
        if status:
            self._ask_panel.set_status(status)

    def reset_conversation(self) -> None:
        if self._ask_panel is not None:
            self._ask_panel.set_context("")
            self._ask_panel.reset_answer()
            self._ask_panel.set_capture(None)

    def answer_chunk(self, text: str) -> None:
        if self._ask_panel is not None:
            self._ask_panel.append_answer(text)

    def answer_status(self, text: str) -> None:
        if self._ask_panel is not None:
            self._ask_panel.set_status(text)

    def answer_reset(self) -> None:
        if self._ask_panel is not None:
            self._ask_panel.reset_answer()

    def answer_finished(self, status: str) -> None:
        if self._ask_panel is not None:
            self._ask_panel.finish(status)

    def answer_failed(self, message: str) -> None:
        if self._ask_panel is not None:
            self._ask_panel.show_error(message)

    # -- approvals, captures, selections ----------------------------------

    def ask_approval(self, request, timeout_seconds: int) -> None:
        if self._approval is None:
            self._approval = ApprovalCard()
            self._protect(self._approval)
            self._approval.decided.connect(self.app._on_approval_decided)
        self._approval.ask(request, timeout_seconds)

    def select_region(self, mode: str) -> None:
        if mode == "text":
            self.app.capture.start_text_region()
        else:
            self.app.capture.start_region()

    def preview_capture(self, capture) -> None:
        if self._capture_preview is None:
            self._capture_preview = CapturePreview()
            self._protect(self._capture_preview)
            self._capture_preview.confirmed.connect(self.app._on_capture_confirmed)
        self._capture_preview.show_capture(capture)

    def choose_selection_action(self, text: str) -> None:
        menu = QMenu()
        for chosen in selection_actions.ACTIONS:
            menu.addAction(chosen.label).setData(chosen.key)
        picked = menu.exec(QCursor.pos())
        if picked is not None:
            self.app._on_selection_action(picked.data())

    def selection_started(self, chosen, text: str) -> None:
        if self._selection_result is None:
            self._selection_result = SelectionResult()
            self._protect(self._selection_result)
            self._selection_result.replace_requested.connect(self.app._replace_selection)
            self._selection_result.copy_requested.connect(
                self.app.clipboard.copy_to_clipboard
            )
        self._selection_result.start(chosen, text)

    def selection_done(self, text: str) -> None:
        if self._selection_result is not None:
            self._selection_result.show_result(text)

    def selection_failed(self, message: str) -> None:
        if self._selection_result is not None:
            self._selection_result.show_error(message)
        else:
            self.notify("Claude", message, "warning")

    def update_sessions(self, sessions: list) -> None:
        self.dock.update_sessions(sessions)

    def _on_dock_clicked(self, session_id: str) -> None:
        app = self.app
        agent = next((a for a in app.agents.agents if a.key == session_id), None)
        menu = QMenu()
        if agent is not None:
            report = menu.addAction("Voir le compte rendu")
            stop = menu.addAction("Arrêter l'agent") if agent.running else None
        else:
            report = stop = None
        dismiss = menu.addAction("Retirer")
        picked = menu.exec(QCursor.pos())
        if picked is None:
            return
        if picked is dismiss:
            app.sessions.forget(session_id)
        elif picked is stop and agent is not None:
            app.agents.stop(agent.id)
        elif picked is report and agent is not None:
            QMessageBox.information(
                None,
                f"Agent · {agent.label}",
                agent.report.strip() or "Pas encore de compte rendu.",
            )

    # -- the guide --------------------------------------------------------

    def guide_point(self, x: float, y: float, label: str) -> None:
        self.overlay.point_at(x, y, label)
        self._fly_towards(x, y)

    def guide_highlight(
        self, left: float, top: float, width: float, height: float, label: str, shape: str
    ) -> None:
        self.overlay.highlight(left, top, width, height, label, shape)

    def guide_steps(self, steps: list) -> None:
        self.overlay.show_steps(steps)

    def guide_clear(self) -> None:
        self.overlay.clear()

    def _fly_towards(self, x: float, y: float) -> None:
        """Send the wizard to stand beside what he is pointing at."""
        if not self.avatar.isVisible():
            return
        if self._home_position is None:
            self._home_position = self.avatar.pos()
        size = self.avatar.width()
        # Stand below-left of the target, so he never covers it, and aim the
        # staff back up at it.
        destination = QPoint(int(x) - size - 24, int(y) + 18)
        screen = self.app.qt.screenAt(QPoint(int(x), int(y)))
        if screen is not None:
            area = screen.availableGeometry()
            destination.setX(max(area.left(), min(destination.x(), area.right() - size)))
            destination.setY(max(area.top(), min(destination.y(), area.bottom() - size)))
        centre = destination + QPoint(size // 2, size // 2)
        dx, dy = x - centre.x(), y - centre.y()
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        self.avatar.set_aim(dx / length, dy / length)
        self.avatar.play_emote(Emote.POINTING)
        animate(self.avatar, b"pos", self.avatar.pos(), destination, 420)

    def _on_overlay_active(self, active: bool) -> None:
        if active or self._home_position is None:
            return
        home, self._home_position = self._home_position, None
        self.avatar.release_emote()
        animate(self.avatar, b"pos", self.avatar.pos(), home, 420)

    # -- windows ----------------------------------------------------------

    def open_window(self, name: str) -> None:
        opener = {
            "quick_note": self._open_quick_note,
            "clipboard": lambda: self._open_history(HistoryPanel.CLIPBOARD_TAB),
            "notes": lambda: self._open_history(HistoryPanel.NOTES_TAB),
            "reminder": self._open_reminder,
            "palette": self._open_palette,
            "settings": self._open_settings,
            "history": self._open_history_window,
            "agent": self._open_agent_dialog,
            "onboarding": self.show_onboarding,
        }.get(name)
        if opener is not None:
            opener()

    def confirm_hooks(self, plan, installing: bool) -> bool:
        if self._hook_dialog is None:
            self._hook_dialog = HookDiffDialog()
        return self._hook_dialog.confirm(plan, installing)

    def show_onboarding(self) -> None:
        # Deferred so the avatar is on screen first: the welcome points at
        # him, and he should be there to be pointed at.
        QTimer.singleShot(600, self._show_onboarding)

    def _show_onboarding(self) -> None:
        app = self.app
        dialog = OnboardingDialog(app.config.hotkeys, app._setup_checks())
        dialog.install_hooks_requested.connect(lambda: app._manage_hooks(True))
        dialog.open_settings_requested.connect(self._open_settings)
        dialog.exec()
        # Marked after, not before: a crash mid-welcome should show it again.
        mark_shown()

    def _open_quick_note(self) -> None:
        if self._note_dialog is None:
            self._note_dialog = QuickNoteDialog(self.app.storage)
            self._note_dialog.accepted.connect(self._refresh_history)
        self._note_dialog.open_near_cursor()

    def _open_history(self, tab: int) -> None:
        if self._history is None:
            self._history = HistoryPanel(self.app.storage)
            self._history.copy_requested.connect(self.app.clipboard.copy_to_clipboard)
            self._history.copy_image_requested.connect(self.app._copy_clip_image)
        self._history.open_at(tab)

    def _refresh_history(self) -> None:
        if self._history is not None and self._history.isVisible():
            self._history.refresh()

    def _open_reminder(self) -> None:
        if self._reminder_dialog is None:
            self._reminder_dialog = ReminderDialog(self.app.timers)
        self._reminder_dialog.open_near_cursor()

    def _open_agent_dialog(self) -> None:
        if self._agent_dialog is None:
            self._agent_dialog = AgentDialog()
            self._protect(self._agent_dialog)
            self._agent_dialog.launched.connect(self.app._launch_agent)
        self._agent_dialog.open_dialog()

    def _open_history_window(self) -> None:
        if self._history_window is None:
            self._history_window = HistoryWindow(self.app.history)
            self._protect(self._history_window)
            self._history_window.resume_requested.connect(self.app._resume_conversation)
        self._history_window.open_history()

    def _open_settings(self) -> None:
        if self._settings is None:
            self._settings = SettingsWindow()
            self._protect(self._settings)
            # Saving writes the file; reloading is what makes it take effect,
            # hotkeys included, without a restart.
            self._settings.saved.connect(self.app.reload_config)
        self._settings.open_settings()

    def _open_palette(self) -> None:
        """One field over everything: actions, launchers, notes, clipboard."""
        app = self.app
        if self._palette is None:
            self._palette = CommandPalette()
            self._protect(self._palette)
            self._palette.source_failed.connect(
                lambda name, why: self.notify(
                    "Palette de commandes",
                    f"La source « {name} » a échoué : {why}",
                    "warning",
                )
            )
            self._palette.add_source("actions", app._action_commands)
            self._palette.add_source("agents", app._agent_commands)
            self._palette.add_dynamic(app._reminder_commands)
            self._palette.add_source("launchers", app._launcher_commands)
            self._palette.add_source("notes", app._note_commands)
            self._palette.add_source("clips", app._clip_commands)
        self._palette.open_palette()
