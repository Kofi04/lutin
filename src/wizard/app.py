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
    LEGACY_AUTOSTART_VALUE,
    ORG_NAME,
)
from .bridge import HookServer
from .bridge import installer as hooks_installer
from .capture.controller import CaptureController
from .character.emote import Emote
from .claude import ClaudeSession, check_auth
from .claude.session import OFFLINE
from .config import (
    Config,
    config_dir,
    database_path,
    ensure_config_file,
    load_config,
)
from .design import ThemeWatcher, stylesheet
from .features.clipboard import ClipboardWatcher
from .features.launcher import LaunchError, launch
from .features.monitor import SystemMonitor
from .features.timers import Reminder, TimerManager
from .hotkeys import GlobalHotkeys
from .mood import Mood, claude_mood_for, combine
from .paths import migrate_legacy_data
from .sessions import EVENT_STATES, SessionRegistry, describe
from .storage import Storage
from .tray import TrayIcon, app_icon
from .ui import HistoryPanel, QuickNoteDialog, ReminderDialog
from .ui_capture import CapturePreview
from .ui_claude import ApprovalCard, AskPanel, ToolRequest
from .ui_hooks import HookDiffDialog, summarise_backup
from .ui_onboarding import Check, OnboardingDialog, already_shown, mark_shown
from .ui_palette import Command, CommandPalette
from .ui_settings import SettingsWindow
from .ui_toast import ToastManager


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

        # Before anything reads a file: carry across the data the app wrote
        # under its previous name. Must happen ahead of ensure_config_file(),
        # or that would create a fresh default config and the copy would then
        # decline to overwrite it.
        self._migration = migrate_legacy_data()

        ensure_config_file()
        self.config: Config = load_config()

        # The theme is applied to the QApplication, so every dialog inherits
        # it and none of them carry a stylesheet of their own any more.
        self.theme = ThemeWatcher()
        self.toasts = ToastManager(self.theme.theme)
        self.theme.changed.connect(self._apply_theme)
        self._apply_theme(self.theme.theme)

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
        self.toasts.set_anchor(self.avatar)
        self._capture_preview: CapturePreview | None = None

        self.claude = ClaudeSession(
            permission_timeout=self.config.claude.permission_timeout_seconds,
            allow_actions=self.config.claude.allow_actions,
            auto_approve_read_only=self.config.claude.auto_approve_read_only,
            prewarm=self.config.claude.enabled and self.config.claude.prewarm,
        )
        self._ask_panel: AskPanel | None = None
        self._approval: ApprovalCard | None = None
        self._approval_queue: deque = deque()
        self._approval_current: int | None = None
        self._auth_checked = False
        self._reported_offline: set[str] = set()
        self._quiet = False
        self._hidden_for_quiet = False

        self.sessions = SessionRegistry()
        self.sessions.changed.connect(self._refresh_mood)
        self._system_mood = Mood.CALM
        self.bridge = HookServer()
        self._hook_dialog: HookDiffDialog | None = None
        # Approvals from the bridge answer a socket, not the SDK, so the
        # queue has to remember which of the two a request came from.
        self._bridge_requests: set[int] = set()

        self._palette: CommandPalette | None = None
        self._settings: SettingsWindow | None = None
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
                "Aucune zone de notification n'est disponible : le sorcier "
                "n'aurait pas de menu.",
            )
            return 1

        winapi.set_app_user_model_id(APP_USER_MODEL_ID)
        winapi.migrate_autostart_value(LEGACY_AUTOSTART_VALUE)

        self.tray.set_autostart(winapi.autostart_enabled())
        self.tray.set_hooks_installed(
            hooks_installer.is_installed(), hooks_installer.is_stale()
        )
        if not self.bridge.start():
            self.notify(
                "Hooks",
                f"Impossible d'ouvrir le canal : {self.bridge.error}",
                kind="warning",
            )
        self.tray.show()
        self.avatar.show()
        self.monitor.start()

        self._report_startup_problems()
        if not already_shown():
            # Deferred so the avatar is on screen first: the welcome points
            # at him, and he should be there to be pointed at.
            from PySide6.QtCore import QTimer

            QTimer.singleShot(600, self._show_onboarding)
        self.avatar.play_emote(Emote.GREETING)
        return self.qt.exec()

    def shutdown(self) -> None:
        self.bridge.stop()
        self.claude.shutdown()
        self.hotkeys.unregister_all()
        self.monitor.stop()
        self.tray.hide()
        self.avatar.hide()
        self.storage.close()
        self.qt.quit()

    # -- wiring -----------------------------------------------------------

    def _apply_theme(self, theme) -> None:
        """Restyle everything at once, including windows already open."""
        self.qt.setStyleSheet(stylesheet(theme))
        self.toasts.set_theme(theme)
        if getattr(self, "_ask_panel", None) is not None:
            self._ask_panel.set_dark(theme.dark)

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
            lambda message: self.notify("Capture", message, kind="warning")
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
        self.claude.connection_changed.connect(self._on_claude_connection)

        self.bridge.event.connect(self._on_hook_event)
        self.bridge.decision_requested.connect(self._on_bridge_decision)
        self.tray.install_hooks_requested.connect(lambda: self._manage_hooks(True))
        self.tray.uninstall_hooks_requested.connect(
            lambda: self._manage_hooks(False)
        )

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
        self.tray.settings_requested.connect(self._open_settings)
        self.tray.open_config_folder_requested.connect(self._open_config_folder)
        self.tray.quit_requested.connect(self.shutdown)

    def _bind_hotkeys(self) -> None:
        hotkeys = self.config.hotkeys
        self.hotkeys.register(hotkeys.quick_note, self._open_quick_note)
        self.hotkeys.register(
            hotkeys.clipboard, lambda: self._open_history(HistoryPanel.CLIPBOARD_TAB)
        )
        self.hotkeys.register(hotkeys.launcher, self._open_palette)
        self.hotkeys.register(hotkeys.toggle_avatar, self._toggle_avatar)
        self.hotkeys.register(hotkeys.capture_region, self.capture.start_region)
        self.hotkeys.register(hotkeys.ask_claude, lambda: self._open_ask(None))

    # -- actions ----------------------------------------------------------

    def _update_quiet_mode(self) -> None:
        """Get out of the way of a game, a video or a presentation.

        Windows already decides when to stop showing its own notifications;
        borrowing that judgement beats comparing window rectangles, which is
        fooled by a maximised window and misses a borderless game.
        """
        quiet = winapi.should_stay_quiet()
        if quiet == self._quiet:
            return
        self._quiet = quiet
        if quiet:
            self._hidden_for_quiet = self.avatar.isVisible()
            self.avatar.hide()
            self.toasts.clear()
        elif self._hidden_for_quiet:
            # Only put him back if we were the ones who hid him: the user
            # may have hidden him deliberately before the game started.
            self._hidden_for_quiet = False
            self.avatar.show()

    def _on_sample(self, sample, mood) -> None:
        self._update_quiet_mode()
        self._system_mood = mood
        self.tray.update_status(sample, mood)
        self._refresh_mood()

    def _refresh_mood(self) -> None:
        """A session waiting on you outranks a busy machine."""
        claude = claude_mood_for([s.state for s in self.sessions.sessions])
        self.avatar.set_mood(combine(self._system_mood, claude))

    def _on_timer_fired(self, reminder: Reminder) -> None:
        self.notify("C'est l'heure", reminder.label)
        self.qt.beep()

    def _on_files_dropped(self, paths: list) -> None:
        # One capture at a time: the preview is a single dialog, and asking
        # about five files at once has no sensible meaning yet.
        if paths:
            self.capture.capture_file(paths[0])
        if len(paths) > 1:
            self.notify(
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
            self.notify("Claude", "Désactivé dans la configuration.", kind="warning")
            return
        if not self._check_auth_once():
            return

        if self._ask_panel is None:
            self._ask_panel = AskPanel()
            self._ask_panel.set_dark(self.theme.theme.dark)
            self._ask_panel.asked.connect(self._on_asked)
            self._ask_panel.interrupted.connect(self.claude.cancel)
        self._ask_panel.open_with(capture)

    def _reset_claude(self) -> None:
        """Forget the conversation and every 'always allow' rule with it."""
        self.claude.reset()
        if self._ask_panel is not None:
            self._ask_panel.reset_answer()
            self._ask_panel.set_capture(None)
        self.notify("Claude", "Nouvelle discussion. Règles oubliées.")

    def _check_auth_once(self) -> bool:
        """Tell the user to log in *before* the SDK fails cryptically."""
        if self._auth_checked:
            return True
        status = check_auth()
        if not status.logged_in:
            self.notify("Claude Code", status.message(), kind="warning")
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
        self.notify("Claude", message, kind="warning")

    # -- approvals --------------------------------------------------------

    def _on_claude_connection(self, state: str, detail: str) -> None:
        """Reflect the link to Claude, without nagging about it.

        Losing the connection is shown on the character and in the tray
        tooltip. Only a problem the user can actually act on — a missing
        login — is worth a notification, and only once.
        """
        self.avatar.set_connection(state)
        self.tray.set_connection(state, detail)
        if state == OFFLINE and detail and detail not in self._reported_offline:
            self._reported_offline.add(detail)
            self.notify("Claude", detail, kind="warning")

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
        if request_id is None:
            self._show_next_approval()
            return

        if request_id in self._bridge_requests:
            self._bridge_requests.discard(request_id)
            # "always" has no equivalent in the hook protocol: allow once, and
            # remember the rule on our side for the next identical request.
            self.bridge.answer(request_id, "allow" if decision != "deny" else "deny")
        else:
            self.claude.answer_permission(request_id, decision)
        self._show_next_approval()

    # -- external sessions (hooks) ----------------------------------------

    def _on_hook_event(self, event) -> None:
        state, feeds = EVENT_STATES.get(event.name, ("idle", False))
        self.sessions.record(
            event.session_id,
            event.project,
            state,
            describe(event) if feeds else "",
        )
        if event.name == "SessionEnd":
            self.sessions.forget(event.session_id)

    def _on_bridge_decision(self, request_id: int, event) -> None:
        self.sessions.record(
            event.session_id, event.project, "waiting", describe(event)
        )
        self._bridge_requests.add(request_id)
        self._approval_queue.append(
            (
                request_id,
                ToolRequest(
                    tool=event.tool_name or "un outil",
                    detail=_tool_detail(event.tool_input),
                    project=event.project,
                ),
            )
        )
        self._show_next_approval()

    # -- hook installation ------------------------------------------------

    def _manage_hooks(self, installing: bool) -> None:
        plan = (
            hooks_installer.plan_install()
            if installing
            else hooks_installer.plan_uninstall()
        )
        if self._hook_dialog is None:
            self._hook_dialog = HookDiffDialog()

        if not self._hook_dialog.confirm(plan, installing):
            return
        if not plan.changed:
            return

        try:
            saved = hooks_installer.apply(plan)
        except OSError as exc:
            self.notify("Hooks", f"Écriture impossible : {exc}", kind="warning")
            return

        installed = hooks_installer.is_installed()
        self.tray.set_hooks_installed(installed)
        self.notify(
            "Hooks installés" if installed else "Hooks retirés",
            summarise_backup(saved),
        )
        if not installed:
            self.sessions.clear()

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

    def _show_onboarding(self) -> None:
        dialog = OnboardingDialog(self.config.hotkeys, self._setup_checks())
        dialog.install_hooks_requested.connect(lambda: self._manage_hooks(True))
        dialog.open_settings_requested.connect(self._open_settings)
        dialog.exec()
        # Marked after, not before: a crash mid-welcome should show it again.
        mark_shown()

    def _setup_checks(self) -> list[Check]:
        """What is and is not ready on this machine, checked, not assumed."""
        auth = check_auth()
        hooks = hooks_installer.is_installed()
        return [
            Check(
                "Claude Code",
                auth.logged_in,
                "Connecté : vous pouvez me poser des questions."
                if auth.logged_in
                else "Pas connecté. Lancez <code>claude auth login</code> dans un "
                "terminal, puis revenez.",
            ),
            Check(
                "Vos sessions Claude Code",
                hooks,
                "Je les vois et vous pouvez approuver leurs actions ici."
                if hooks
                else "Pas encore reliées. Rien n'est modifié sans que vous voyiez "
                "le changement exact avant.",
                action="" if hooks else "Installer…",
            ),
            Check(
                "Icône de notification",
                True,
                "Sous Windows 10, elle se range derrière la flèche <b>^</b> près "
                "de l'horloge. Glissez-la sur la barre pour la garder visible.",
            ),
        ]

    def _open_settings(self) -> None:
        if self._settings is None:
            self._settings = SettingsWindow()
            # Saving writes the file; reloading is what makes it take effect,
            # hotkeys included, without a restart.
            self._settings.saved.connect(self.reload_config)
        self._settings.open_settings()

    def _open_palette(self) -> None:
        """One field over everything: actions, launchers, notes, clipboard."""
        if self._palette is None:
            self._palette = CommandPalette()
            self._palette.source_failed.connect(
                lambda name, why: self.notify(
                    "Palette de commandes",
                    f"La source « {name} » a échoué : {why}",
                    kind="warning",
                )
            )
            self._palette.add_source("actions", self._action_commands)
            self._palette.add_source("launchers", self._launcher_commands)
            self._palette.add_source("notes", self._note_commands)
            self._palette.add_source("clips", self._clip_commands)
        self._palette.open_palette()

    def _action_commands(self) -> list[Command]:
        entries = [
            ("Demander à Claude…", lambda: self._open_ask(None), "question ia chat"),
            ("Montrer une zone…", self.capture.start_region, "capture ecran zone"),
            ("Note rapide", self._open_quick_note, "ecrire memo"),
            (
                "Presse-papiers",
                lambda: self._open_history(HistoryPanel.CLIPBOARD_TAB),
                "copier historique",
            ),
            (
                "Notes",
                lambda: self._open_history(HistoryPanel.NOTES_TAB),
                "historique memo",
            ),
            ("Me rappeler…", self._open_reminder, "minuteur timer pomodoro"),
            ("Nouvelle discussion Claude", self._reset_claude, "reset effacer"),
            ("Paramètres…", self._open_settings, "reglages options preferences"),
            (
                "Masquer / Afficher le sorcier",
                self._toggle_avatar,
                "cacher montrer avatar",
            ),
            ("Replacer sur la barre", self.avatar.snap_to_taskbar, "position"),
            (
                "Recharger la configuration",
                self.reload_config,
                "config toml reglages",
            ),
            (
                "Ouvrir le dossier de configuration",
                self._open_config_folder,
                "dossier fichiers",
            ),
        ]
        return [
            Command(
                title=title, kind="action", run=run, keywords=keywords, order=index
            )
            for index, (title, run, keywords) in enumerate(entries)
        ]

    def _launcher_commands(self) -> list[Command]:
        return [
            Command(
                title=entry.label,
                kind="launcher",
                subtitle=entry.target,
                run=lambda item=entry: self._launch(item),
                order=100 + index,
            )
            for index, entry in enumerate(self.config.launcher)
        ]

    def _note_commands(self) -> list[Command]:
        return [
            Command(
                title=_one_line(record.body),
                kind="note",
                run=lambda body=record.body: self.clipboard.copy_to_clipboard(body),
                order=200 + index,
            )
            for index, record in enumerate(self.storage.list_notes(limit=60))
        ]

    def _clip_commands(self) -> list[Command]:
        return [
            Command(
                title=_one_line(record.body),
                kind="clip",
                run=lambda body=record.body: self.clipboard.copy_to_clipboard(body),
                order=300 + index,
            )
            for index, record in enumerate(self.storage.list_clips(limit=60))
        ]

    def _launch(self, entry) -> None:
        try:
            launch(entry)
        except LaunchError as exc:
            self.notify(
                f"Impossible de lancer {entry.label}", str(exc), kind="warning"
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
            self.notify(
                "Démarrage automatique inchangé",
                "Windows a refusé la modification de l'entrée de démarrage.",
                kind="warning",
            )

    def _open_config_folder(self) -> None:
        try:
            os.startfile(config_dir())  # type: ignore[attr-defined]
        except OSError as exc:
            self.notify("Impossible d'ouvrir le dossier", str(exc), kind="warning")

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

    def notify(self, title: str, body: str = "", kind: str = "info") -> None:
        """One way to tell the user something, themed and in our control."""
        self.toasts.show(title, body, kind)

    def _report_startup_problems(self, reloaded: bool = False) -> None:
        if not reloaded:
            self._report_rename()
        problems = list(self.config.warnings) + self.hotkeys.failures
        if problems:
            self.notify(
                "Configuration chargée avec des avertissements",
                "\n".join(problems[:4]),
                kind="warning",
            )
        elif reloaded:
            self.notify(
                "Configuration rechargée", "Tous les réglages ont été appliqués."
            )

    def _report_rename(self) -> None:
        """Tell the user what the rename did, once, and only if it did something."""
        summary = self._migration.summary()
        if summary:
            self.notify(f"Bienvenue dans {APP_NAME}", summary)
        if self._migration.failures:
            self.notify(
                "Récupération incomplète",
                "\n".join(self._migration.failures[:3]),
                kind="warning",
            )
        if hooks_installer.is_stale():
            # The hooks point at a script that has moved or been renamed, so
            # every tool call in your terminals is starting a process that dies.
            self.notify(
                "Hooks à réinstaller",
                "Les hooks Claude Code pointent vers l'ancien emplacement. "
                "Choisissez « Installer les hooks Claude Code… » pour les "
                "remettre à jour.",
                kind="warning",
            )


def main(argv: list[str] | None = None) -> int:
    app = AvatarApp(list(argv if argv is not None else sys.argv))
    return app.run()


def _one_line(body: str, limit: int = 90) -> str:
    """Collapse a note or a clipboard entry onto one readable line."""
    single = " ".join(body.split())
    return single if len(single) <= limit else single[: limit - 1] + "…"


def _tool_detail(tool_input: dict) -> str:
    """What exactly a hooked session is about to do, for the approval card."""
    for key in ("command", "file_path", "path", "url", "pattern"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    try:
        import json as _json

        return _json.dumps(tool_input, ensure_ascii=False, indent=2)[:2000]
    except (TypeError, ValueError):
        return str(tool_input)[:2000]
