"""Application wiring: builds every part and connects them together.

Nothing in here implements a feature; it only decides who talks to whom. That
keeps the feature modules independently testable and makes the data flow easy
to follow:

    SystemMonitor --(Sample, Mood)--> TrayIcon + AvatarWindow
    ClipboardWatcher --> Storage --> HistoryPanel --> ClipboardWatcher
    GlobalHotkeys / TrayIcon / AvatarWindow --> the dialogs
"""

from __future__ import annotations

import os
import sys
from collections import deque

from PySide6.QtCore import QSharedMemory, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import winapi
from .avatar_window import AvatarWindow
from .branding import (
    APP_NAME,
    APP_USER_MODEL_ID,
    INSTANCE_KEY,
    ORG_NAME,
)
from .capture.controller import CaptureController
from .claude import ClaudeSession, check_auth
from .config import (
    Config,
    config_dir,
    database_path,
    ensure_config_file,
    load_config,
)
from .features.clipboard import ClipboardWatcher
from .features.launcher import LaunchError, launch
from .features.monitor import SystemMonitor
from .features.timers import Reminder, TimerManager
from .hotkeys import GlobalHotkeys
from .storage import Storage
from .tray import TrayIcon, app_icon
from .ui import HistoryPanel, QuickNoteDialog, ReminderDialog
from .ui_capture import CapturePreview
from .ui_claude import ApprovalCard, AskPanel


class AvatarApp:
    """Owns the QApplication and the object graph around it."""

    def __init__(self, argv: list[str]) -> None:
        # Fractional display scaling (125%, 150%) stays fractional instead of
        # being rounded, which keeps the avatar the size the config asks for.
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        self.qt = QApplication(argv)
        self.qt.setApplicationName(APP_NAME)
        self.qt.setOrganizationName(ORG_NAME)
        # Without this the dialogs wear the generic Python feather in their
        # title bar and in Alt+Tab.
        self.qt.setWindowIcon(app_icon())
        # The app has no main window, so closing a dialog must not quit it.
        self.qt.setQuitOnLastWindowClosed(False)

        # Held as an attribute: releasing it would free the lock.
        self._instance_lock = QSharedMemory(INSTANCE_KEY)
        self._already_running = not self._instance_lock.create(1)

        ensure_config_file()
        self.config: Config = load_config()

        self.storage = Storage(database_path())
        self.timers = TimerManager()
        self.monitor = SystemMonitor(self.config.monitor)
        self.clipboard = ClipboardWatcher(self.storage, self.config.clipboard)

        self.avatar = AvatarWindow(self.config.appearance)
        self.tray = TrayIcon(self.config, self.timers)

        self.capture = CaptureController()
        # The avatar is always-on-top, so without this the window lookup would
        # only ever find the avatar itself.
        self.capture.ignore_window(self.avatar)
        self._capture_preview: CapturePreview | None = None

        self.claude = ClaudeSession(
            permission_timeout=self.config.claude.permission_timeout_seconds,
            allow_actions=self.config.claude.allow_actions,
            auto_approve_read_only=self.config.claude.auto_approve_read_only,
        )
        self._ask_panel: AskPanel | None = None
        self._approval: ApprovalCard | None = None
        self._approval_queue: deque = deque()
        self._approval_current: int | None = None
        self._auth_checked = False

        self._note_dialog: QuickNoteDialog | None = None
        self._history: HistoryPanel | None = None
        self._reminder_dialog: ReminderDialog | None = None

        self.hotkeys = GlobalHotkeys()
        self.qt.installNativeEventFilter(self.hotkeys)

        self._connect()
        self._bind_hotkeys()

    # -- lifecycle --------------------------------------------------------

    def run(self) -> int:
        if self._already_running:
            QMessageBox.information(
                None,
                APP_NAME,
                f"{APP_NAME} est déjà lancé — cherchez-le dans la zone "
                "de notification, près de l'horloge.",
            )
            return 0

        if not QSystemTrayIcon.isSystemTrayAvailable():
            QMessageBox.critical(
                None,
                APP_NAME,
                "Aucune zone de notification n'est disponible : le lutin "
                "n'aurait pas de menu.",
            )
            return 1

        winapi.set_app_user_model_id(APP_USER_MODEL_ID)

        self.tray.set_autostart(winapi.autostart_enabled())
        self.tray.show()
        self.avatar.show()
        self.monitor.start()

        self._report_startup_problems()
        return self.qt.exec()

    def shutdown(self) -> None:
        self.claude.shutdown()
        self.hotkeys.unregister_all()
        self.monitor.stop()
        self.tray.hide()
        self.avatar.hide()
        self.storage.close()
        self.qt.quit()

    # -- wiring -----------------------------------------------------------

    def _connect(self) -> None:
        self.monitor.sampled.connect(self._on_sample)

        self.timers.fired.connect(self._on_timer_fired)

        self.avatar.clicked.connect(self._show_action_menu_at_avatar)
        self.avatar.context_menu_requested.connect(self.tray.popup_menu)
        self.avatar.targeting_started.connect(self.capture.start_targeting)
        self.avatar.targeting_moved.connect(self.capture.update_target)
        self.avatar.targeting_finished.connect(self.capture.finish_targeting)
        self.avatar.targeting_cancelled.connect(self.capture.cancel_targeting)
        self.avatar.files_dropped.connect(self._on_files_dropped)

        self.capture.captured.connect(self._preview_capture)
        self.capture.failed.connect(
            lambda message: self.tray.notify("Capture", message, warning=True)
        )
        self.tray.capture_region_requested.connect(self.capture.start_region)
        self.tray.ask_claude_requested.connect(lambda: self._open_ask(None))
        self.tray.reset_claude_requested.connect(self._reset_claude)

        self.claude.chunk.connect(self._on_claude_chunk)
        self.claude.activity.connect(self._on_claude_activity)
        self.claude.finished.connect(self._on_claude_finished)
        self.claude.failed.connect(self._on_claude_failed)
        self.claude.reset_answer.connect(self._on_claude_reset)
        self.claude.permission_requested.connect(self._on_permission_requested)

        self.tray.quick_note_requested.connect(self._open_quick_note)
        self.tray.clipboard_requested.connect(
            lambda: self._open_history(HistoryPanel.CLIPBOARD_TAB)
        )
        self.tray.notes_requested.connect(
            lambda: self._open_history(HistoryPanel.NOTES_TAB)
        )
        self.tray.reminder_requested.connect(self._open_reminder)
        self.tray.launch_requested.connect(self._launch)
        self.tray.cancel_timer_requested.connect(self.timers.cancel)
        self.tray.toggle_avatar_requested.connect(self._toggle_avatar)
        self.tray.snap_requested.connect(self.avatar.snap_to_taskbar)
        self.tray.reset_position_requested.connect(self.avatar.forget_position)
        self.tray.clipboard_capture_toggled.connect(self.clipboard.set_enabled)
        self.tray.autostart_toggled.connect(self._set_autostart)
        self.tray.reload_config_requested.connect(self.reload_config)
        self.tray.open_config_folder_requested.connect(self._open_config_folder)
        self.tray.quit_requested.connect(self.shutdown)

    def _bind_hotkeys(self) -> None:
        hotkeys = self.config.hotkeys
        self.hotkeys.register(hotkeys.quick_note, self._open_quick_note)
        self.hotkeys.register(
            hotkeys.clipboard, lambda: self._open_history(HistoryPanel.CLIPBOARD_TAB)
        )
        self.hotkeys.register(hotkeys.launcher, self._show_launcher_menu)
        self.hotkeys.register(hotkeys.toggle_avatar, self._toggle_avatar)
        self.hotkeys.register(hotkeys.capture_region, self.capture.start_region)
        self.hotkeys.register(hotkeys.ask_claude, lambda: self._open_ask(None))

    # -- actions ----------------------------------------------------------

    def _on_sample(self, sample, mood) -> None:
        self.tray.update_status(sample, mood)
        self.avatar.set_mood(mood)

    def _on_timer_fired(self, reminder: Reminder) -> None:
        self.tray.notify("C'est l'heure", reminder.label)
        self.qt.beep()

    def _on_files_dropped(self, paths: list) -> None:
        # One capture at a time: the preview is a single dialog, and asking
        # about five files at once has no sensible meaning yet.
        if paths:
            self.capture.capture_file(paths[0])
        if len(paths) > 1:
            self.tray.notify(
                "Capture",
                f"{len(paths)} fichiers déposés, je ne garde que le premier.",
            )

    def _preview_capture(self, capture) -> None:
        if self._capture_preview is None:
            self._capture_preview = CapturePreview()
            self._capture_preview.confirmed.connect(self._on_capture_confirmed)
        self._capture_preview.show_capture(capture)

    def _on_capture_confirmed(self, capture) -> None:
        self._open_ask(capture)

    # -- Claude -----------------------------------------------------------

    def _open_ask(self, capture) -> None:
        if not self.config.claude.enabled:
            self.tray.notify("Claude", "Désactivé dans la configuration.", warning=True)
            return
        if not self._check_auth_once():
            return

        if self._ask_panel is None:
            self._ask_panel = AskPanel()
            self._ask_panel.asked.connect(self._on_asked)
            self._ask_panel.interrupted.connect(self.claude.cancel)
        self._ask_panel.open_with(capture)

    def _reset_claude(self) -> None:
        """Forget the conversation and every 'always allow' rule with it."""
        self.claude.reset()
        if self._ask_panel is not None:
            self._ask_panel.reset_answer()
            self._ask_panel.set_capture(None)
        self.tray.notify("Claude", "Nouvelle discussion. Règles oubliées.")

    def _check_auth_once(self) -> bool:
        """Tell the user to log in *before* the SDK fails cryptically."""
        if self._auth_checked:
            return True
        status = check_auth()
        if not status.logged_in:
            self.tray.notify("Claude Code", status.message(), warning=True)
            return False
        self._auth_checked = True
        return True

    def _on_asked(self, question: str, capture) -> None:
        self.claude.ask(question, capture)

    def _on_claude_chunk(self, text: str) -> None:
        if self._ask_panel is not None:
            self._ask_panel.append_answer(text)

    def _on_claude_activity(self, line: str) -> None:
        if self._ask_panel is not None:
            self._ask_panel.set_status(line)

    def _on_claude_finished(self, status: str) -> None:
        if self._ask_panel is not None:
            self._ask_panel.finish(status)

    def _on_claude_reset(self) -> None:
        if self._ask_panel is not None:
            self._ask_panel.reset_answer()

    def _on_claude_failed(self, message: str) -> None:
        if self._ask_panel is not None:
            self._ask_panel.show_error(message)
        self.tray.notify("Claude", message, warning=True)

    # -- approvals --------------------------------------------------------

    def _on_permission_requested(self, request_id: int, request) -> None:
        self._approval_queue.append((request_id, request))
        self._show_next_approval()

    def _show_next_approval(self) -> None:
        if self._approval_current is not None or not self._approval_queue:
            return

        if self._approval is None:
            self._approval = ApprovalCard()
            self._approval.decided.connect(self._on_approval_decided)

        request_id, request = self._approval_queue.popleft()
        self._approval_current = request_id
        self._approval.ask(request, self.config.claude.permission_timeout_seconds)

    def _on_approval_decided(self, decision: str) -> None:
        request_id, self._approval_current = self._approval_current, None
        if request_id is not None:
            self.claude.answer_permission(request_id, decision)
        self._show_next_approval()

    def _open_quick_note(self) -> None:
        if self._note_dialog is None:
            self._note_dialog = QuickNoteDialog(self.storage)
            self._note_dialog.accepted.connect(self._refresh_history)
        self._note_dialog.open_near_cursor()

    def _open_history(self, tab: int) -> None:
        if self._history is None:
            self._history = HistoryPanel(self.storage)
            self._history.copy_requested.connect(self.clipboard.copy_to_clipboard)
        self._history.open_at(tab)

    def _refresh_history(self) -> None:
        if self._history is not None and self._history.isVisible():
            self._history.refresh()

    def _open_reminder(self) -> None:
        if self._reminder_dialog is None:
            self._reminder_dialog = ReminderDialog(self.timers)
        self._reminder_dialog.open_near_cursor()

    def _show_action_menu_at_avatar(self) -> None:
        # Anchor the menu to the avatar's top-left so it opens over the desktop
        # rather than off the bottom of the screen.
        self.tray.popup_menu(self.avatar.mapToGlobal(self.avatar.rect().topLeft()))

    def _show_launcher_menu(self) -> None:
        from PySide6.QtGui import QCursor

        menu = self.tray.launcher_menu()
        menu.exec(QCursor.pos())

    def _launch(self, entry) -> None:
        try:
            launch(entry)
        except LaunchError as exc:
            self.tray.notify(
                f"Impossible de lancer {entry.label}", str(exc), warning=True
            )

    def _toggle_avatar(self) -> None:
        visible = not self.avatar.isVisible()
        self.avatar.setVisible(visible)
        self.tray.set_avatar_visible(visible)

    def _set_autostart(self, enabled: bool) -> None:
        winapi.set_autostart(enabled)
        actual = winapi.autostart_enabled()
        self.tray.set_autostart(actual)
        if actual != enabled:
            self.tray.notify(
                "Démarrage automatique inchangé",
                "Windows a refusé la modification de l'entrée de démarrage.",
                warning=True,
            )

    def _open_config_folder(self) -> None:
        try:
            os.startfile(config_dir())  # type: ignore[attr-defined]
        except OSError as exc:
            self.tray.notify("Impossible d'ouvrir le dossier", str(exc), warning=True)

    def reload_config(self) -> None:
        """Re-read config.toml and apply what can be applied without a restart."""
        self.config = load_config()

        self.avatar.apply_appearance(self.config.appearance)
        self.monitor.apply_settings(self.config.monitor)
        self.clipboard.apply_settings(self.config.clipboard)
        self.tray.apply_config(self.config)

        # Hotkeys must be dropped and re-registered: Win32 has no "rebind".
        self.hotkeys.unregister_all()
        self._bind_hotkeys()

        self._report_startup_problems(reloaded=True)

    def _report_startup_problems(self, reloaded: bool = False) -> None:
        problems = list(self.config.warnings) + self.hotkeys.failures
        if problems:
            self.tray.notify(
                "Configuration chargée avec des avertissements",
                "\n".join(problems[:4]),
                warning=True,
            )
        elif reloaded:
            self.tray.notify(
                "Configuration rechargée", "Tous les réglages ont été appliqués."
            )


def main(argv: list[str] | None = None) -> int:
    app = AvatarApp(list(argv if argv is not None else sys.argv))
    return app.run()
