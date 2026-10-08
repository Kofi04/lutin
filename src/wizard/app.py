"""Application wiring: builds every part and connects them together.

Nothing in here implements a feature; it only decides who talks to whom. That
keeps the feature modules independently testable and makes the data flow easy
to follow:

    SystemMonitor --(Sample, Mood)--> the presenter
    ClipboardWatcher --> Storage --> services.py --> the app window
    GlobalHotkeys / the Tauri UI's commands --> the features

Nothing here touches a widget: the core has no window. What to show goes
through `self.ui`, the presenter (presenter_remote.py), which turns it into
protocol events for the Tauri UI over a local WebSocket.
"""

from __future__ import annotations

import os
import sys
from collections import deque

from PySide6.QtCore import QObject, QSharedMemory, Qt, Signal
from PySide6.QtWidgets import QApplication

from . import services, winapi
from .assistant import memory as user_memory
from .assistant import ocr
from .assistant import selection as selection_actions
from .assistant.agents import AgentError, AgentManager
from .assistant.selection import SelectionBridge
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
from .claude import ClaudeSession, check_auth
from .claude.session import OFFLINE
from .claude.tool_request import ToolRequest
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
from .history import CaptureInfo, HistoryStore
from .hotkeys import GlobalHotkeys
from .mood import Mood, claude_mood_for, combine
from .onboarding import Check, already_shown
from .paths import migrate_legacy_data
from .presenter import Presenter
from .rpc import Rpc
from .sessions import EVENT_STATES, SessionRegistry, describe
from .storage import Storage


class _Relay(QObject):
    """Carries results from worker threads back to the GUI thread."""

    text_read = Signal(str, str)  # (text, error)


class AvatarApp:
    """Owns the QApplication and the object graph around it."""

    def __init__(self, argv: list[str], presenter: Presenter) -> None:
        # Fractional display scaling (125%, 150%) stays fractional instead of
        # being rounded, which keeps the avatar the size the config asks for.
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        # Reuse an existing instance (the test suite has one): Qt allows a
        # single QApplication per process.
        self.qt = QApplication.instance() or QApplication(argv)
        self.qt.setApplicationName(APP_NAME)
        self.qt.setOrganizationName(ORG_NAME)
        # No window at all (the Tauri UI draws everything): nothing closing
        # may quit the core.
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

        self.ui = presenter
        #: What the Tauri UI may ask of the core (rpc.py, services.py).
        self.rpc = Rpc()
        self._escape_id: int | None = None

        self.storage = Storage(database_path())
        self.history = HistoryStore(self.storage.connection)
        if self.config.history.enabled:
            self.history.purge_older_than(self.config.history.retention_days)
        #: The conversation the answer panel is currently part of.
        self._conversation_id: int | None = None
        self._answer_buffer = ""
        self._approval_request = None
        #: One-shot Claude jobs in flight: job id -> what to do with the result.
        self._jobs: dict[int, tuple] = {}
        self._relay = _Relay()
        self._ocr_result = self._relay.text_read
        self._next_job = 1
        self._selection_pending: tuple[str, int] | None = None
        self.timers = TimerManager()
        self.monitor = SystemMonitor(self.config.monitor)
        self.clipboard = ClipboardWatcher(self.storage, self.config.clipboard)
        self.selection = SelectionBridge(
            hold=self.clipboard.hold, release=self.clipboard.release
        )
        self._selection_source = 0
        services.register(self.rpc, self)

        self.capture = CaptureController(cloak=self.ui.make_cloak())

        self.claude = ClaudeSession(
            permission_timeout=self.config.claude.permission_timeout_seconds,
            allow_actions=self.config.claude.allow_actions,
            auto_approve_read_only=self.config.claude.auto_approve_read_only,
            prewarm=self.config.claude.enabled and self.config.claude.prewarm,
            memory=user_memory.for_prompt(user_memory.load_memory()),
        )
        self._approval_queue: deque = deque()
        self._approval_current: int | None = None
        self._auth_checked = False
        self._reported_offline: set[str] = set()
        self._quiet = False

        self.sessions = SessionRegistry()
        self.sessions.changed.connect(self._refresh_mood)
        self.agents = AgentManager(self.config.claude.permission_timeout_seconds)
        self._apply_memory()
        self._system_mood = Mood.CALM
        self.bridge = HookServer()
        # Approvals from the bridge answer a socket, not the SDK, so the
        # queue has to remember which of the two a request came from.
        self._approval_owner = None

        self.hotkeys = GlobalHotkeys()
        self.qt.installNativeEventFilter(self.hotkeys)

        self.ui.bind(self)
        self._connect()
        self._bind_hotkeys()

    # -- lifecycle --------------------------------------------------------

    def run(self) -> int:
        if self._already_running:
            return self.ui.report_already_running()
        failed = self.ui.preflight()
        if failed is not None:
            return failed

        winapi.set_app_user_model_id(APP_USER_MODEL_ID)
        winapi.migrate_autostart_value(LEGACY_AUTOSTART_VALUE)

        self.ui.set_flags(
            autostart=winapi.autostart_enabled(),
            hooks_installed=hooks_installer.is_installed(),
            hooks_stale=hooks_installer.is_stale(),
        )
        if not self.bridge.start():
            self.notify(
                "Hooks",
                f"Impossible d'ouvrir le canal : {self.bridge.error}",
                kind="warning",
            )
        self.ui.start()
        self.monitor.start()

        self._report_startup_problems()
        if not already_shown():
            self.ui.show_onboarding()
        return self.qt.exec()

    def shutdown(self) -> None:
        self.agents.shutdown()
        self.bridge.stop()
        self.claude.shutdown()
        self.hotkeys.unregister_all()
        self.monitor.stop()
        self.ui.stop()
        self.storage.close()
        self.qt.quit()

    # -- wiring -----------------------------------------------------------

    def _connect(self) -> None:
        self.monitor.sampled.connect(self._on_sample)

        self.timers.fired.connect(self._on_timer_fired)

        self.capture.captured.connect(self.ui.preview_capture)
        self.capture.failed.connect(
            lambda message: self.notify("Capture", message, kind="warning")
        )

        self.claude.chunk.connect(self._on_claude_chunk)
        self.claude.activity.connect(self._on_claude_activity)
        self.claude.finished.connect(self._on_claude_finished)
        self.claude.failed.connect(self._on_claude_failed)
        self.claude.reset_answer.connect(self._on_claude_reset)
        self.claude.permission_requested.connect(self._on_permission_requested)
        self.claude.connection_changed.connect(self._on_claude_connection)
        self.claude.oneshot_done.connect(self._on_job_done)
        self.sessions.changed.connect(
            lambda: self.ui.update_sessions(self.sessions.sessions)
        )
        self.capture.text_region.connect(self._read_text)
        self._ocr_result.connect(self._on_text_read)
        self.agents.progressed.connect(self._on_agent_progress)
        self.agents.permission_requested.connect(self._on_agent_permission)
        self.agents.ended.connect(self._on_agent_ended)
        self.claude.oneshot_failed.connect(self._on_job_failed)
        self.selection.grabbed.connect(self._on_selection_grabbed)
        self.selection.failed.connect(
            lambda message: self.notify("Sélection", message, kind="warning")
        )
        self.claude.overlay.point_requested.connect(self.ui.guide_point)
        self.claude.overlay.highlight_requested.connect(self.ui.guide_highlight)
        self.claude.overlay.steps_requested.connect(self.ui.guide_steps)
        self.claude.overlay.clear_requested.connect(self.ui.guide_clear)
        self.claude.overlay.reminder_requested.connect(self._set_reminder)

        self.bridge.event.connect(self._on_hook_event)
        self.bridge.decision_requested.connect(self._on_bridge_decision)

    def _bind_hotkeys(self) -> None:
        hotkeys = self.config.hotkeys
        self.hotkeys.register(hotkeys.quick_note, self._open_quick_note)
        self.hotkeys.register(hotkeys.clipboard, lambda: self.ui.open_window("clipboard"))
        self.hotkeys.register(hotkeys.launcher, self._open_palette)
        self.hotkeys.register(hotkeys.toggle_avatar, self._toggle_avatar)
        self.hotkeys.register(hotkeys.capture_region, lambda: self._start_region("ask"))
        self.hotkeys.register(hotkeys.ask_claude, lambda: self._open_ask(None))
        self.hotkeys.register(hotkeys.capture_screen, self.capture.capture_active_screen)
        self.hotkeys.register(hotkeys.selection_actions, self._start_selection)
        self.hotkeys.register(hotkeys.copy_text, self._start_text_copy)

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
        self.ui.set_quiet(quiet)

    def _on_sample(self, sample, mood) -> None:
        self._update_quiet_mode()
        self._system_mood = mood
        self.ui.update_system(sample, mood)
        self._refresh_mood()

    def _refresh_mood(self) -> None:
        """A session waiting on you outranks a busy machine."""
        claude = claude_mood_for([s.state for s in self.sessions.sessions])
        self.ui.set_mood(combine(self._system_mood, claude))

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

    def _start_region(self, mode: str) -> None:
        """Let the user draw a rectangle: to ask about it, or to read its text."""
        self.ui.select_region(mode)

    def _on_capture_confirmed(self, capture) -> None:
        self._open_ask(capture)

    # -- Claude -----------------------------------------------------------

    def _open_ask(self, capture, context: str | None = None, status: str = "") -> bool:
        if not self.config.claude.enabled:
            self.notify("Claude", "Désactivé dans la configuration.", kind="warning")
            return False
        if not self._check_auth_once():
            return False
        self.ui.open_ask(capture, context, status)
        return True

    def _reset_claude(self) -> None:
        """Forget the conversation and every 'always allow' rule with it."""
        self.claude.reset()
        self._conversation_id = None
        self.ui.reset_conversation()
        self.notify("Claude", "Nouvelle discussion. Règles oubliées.")

    # -- reminders in plain words ----------------------------------------

    def _copy_clip_image(self, clip_id: int) -> None:
        png = self.storage.clip_image(clip_id)
        if png is not None:
            self.clipboard.copy_image_to_clipboard(png)

    def _set_reminder(self, seconds: int, label: str) -> None:
        from .features.nl_reminder import ParsedReminder

        self.timers.add(label, seconds)
        self.notify(
            ParsedReminder(seconds, label).describe(),
            "Gardé en mémoire : perdu si l'app est fermée avant.",
            kind="success",
        )

    # -- copying the text in a region (local OCR) -------------------------

    def _start_text_copy(self) -> None:
        if not ocr.available():
            self.notify(
                "Copier le texte",
                "La reconnaissance de texte n'est pas installée : "
                'pip install -e ".[ocr]"',
                kind="warning",
            )
            return
        self._start_region("text")

    def _read_text(self, image) -> None:
        import threading

        png = ocr.prepare_png(image)

        def work() -> None:
            try:
                self._ocr_result.emit(ocr.recognize_png(png), "")
            except RuntimeError as exc:
                self._ocr_result.emit("", str(exc))

        threading.Thread(target=work, name="wizard-ocr-job", daemon=True).start()

    def _on_text_read(self, text: str, error: str) -> None:
        if error:
            self.notify("Copier le texte", error, kind="warning")
        elif not text.strip():
            self.notify("Copier le texte", "Aucun texte reconnu dans cette zone.")
        else:
            self.clipboard.copy_to_clipboard(text)
            self.notify("Texte copié", _one_line(text, 140), kind="success")

    # -- background agents ------------------------------------------------

    def _open_agent_dialog(self) -> None:
        if not self.config.claude.enabled or not self._check_auth_once():
            return
        self.ui.open_window("agent")

    def _launch_agent(self, task: str, folder: str) -> None:
        try:
            agent = self.agents.start(task, folder)
        except AgentError as exc:
            self.notify("Agent", str(exc), kind="warning")
            return
        if self.config.history.enabled:
            agent.conversation_id = self.history.start("agent", project=agent.label)
            self.history.add_message(
                agent.conversation_id, "user", f"{task}\n\n(dossier : {agent.folder})"
            )
        self.notify("Agent lancé", f"{agent.label} : {_one_line(task, 70)}")

    def _apply_memory(self) -> None:
        """Hand memory.md to Claude: the main session and new agents."""
        text = user_memory.for_prompt(user_memory.load_memory())
        self.claude.set_memory(text)
        self.agents.memory = text

    def _on_agent_progress(self, agent, state: str, line: str) -> None:
        self.sessions.record(agent.key, f"Agent · {agent.label}", state, line)

    def _on_agent_permission(self, agent, request_id: int, request) -> None:
        from dataclasses import replace

        labelled = replace(request, project=f"l'agent « {agent.label} »")
        self._approval_queue.append((agent.session, request_id, labelled))
        self._show_next_approval()

    def _on_agent_ended(self, agent) -> None:
        from PySide6.QtCore import QTimer

        titles = {
            "done": "Agent terminé",
            "failed": "Agent en échec",
            "stopped": "Agent arrêté",
        }
        summary = _one_line(agent.report or agent.last_action or "", 160)
        kind = "warning" if agent.state == "failed" else "success"
        self.notify(
            titles.get(agent.state, "Agent"), f"{agent.label} — {summary}", kind=kind
        )
        if self.config.history.enabled and agent.conversation_id is not None:
            role = "error" if agent.state == "failed" else "assistant"
            if agent.report.strip():
                self.history.add_message(agent.conversation_id, role, agent.report)
            if agent.session.session_id:
                self.history.set_session(agent.conversation_id, agent.session.session_id)
        # Leave the mini-wizard up long enough to be noticed, then tidy up.
        QTimer.singleShot(60_000, lambda key=agent.key: self.sessions.forget(key))

    # -- actions on the selected text ------------------------------------

    def _start_selection(self) -> None:
        if not self.config.claude.enabled or not self._check_auth_once():
            return
        self.selection.grab()

    def _on_selection_grabbed(self, text: str, source: int) -> None:
        self._selection_pending = (text, source)
        self.ui.choose_selection_action(text)

    def _on_selection_action(self, key: str) -> None:
        """The user picked what to do with the text grabbed last."""
        if self._selection_pending is None:
            return
        try:
            chosen = selection_actions.action(key)
        except KeyError:
            return
        text, source = self._selection_pending
        self._selection_pending = None
        self._selection_source = source
        self.ui.selection_started(chosen, text)
        self._run_job(
            ("selection", chosen, text),
            selection_actions.build_prompt(chosen, text),
            selection_actions.SYSTEM_PROMPT,
        )

    def _replace_selection(self, text: str) -> None:
        self.selection.replace(self._selection_source, text)

    def _run_job(self, purpose: tuple, prompt: str, system_prompt: str) -> None:
        job_id, self._next_job = self._next_job, self._next_job + 1
        self._jobs[job_id] = purpose
        self.claude.run_oneshot(job_id, prompt, system_prompt)

    def _on_job_done(self, job_id: int, text: str) -> None:
        purpose = self._jobs.pop(job_id, None)
        if purpose is None:
            return
        if purpose[0] == "selection":
            _, chosen, original = purpose
            result = selection_actions.clean_result(text)
            self.ui.selection_done(result)
            if self.config.history.enabled:
                cid = self.history.start("selection", chosen.label)
                self.history.add_message(cid, "user", original)
                self.history.add_message(cid, "assistant", result)

    def _on_job_failed(self, job_id: int, message: str) -> None:
        purpose = self._jobs.pop(job_id, None)
        if purpose is None:
            return
        if purpose[0] == "selection":
            self.ui.selection_failed(message)
        else:
            self.notify("Claude", message, kind="warning")

    def _record_answer(self, role: str, body: str) -> None:
        """Store Claude's side of the turn, and the session id to resume it."""
        self._answer_buffer = ""
        if not self.config.history.enabled or self._conversation_id is None:
            return
        if body.strip():
            self.history.add_message(self._conversation_id, role, body)
        if self.claude.session_id:
            self.history.set_session(self._conversation_id, self.claude.session_id)

    def _open_history_window(self) -> None:
        self.ui.open_window("history")

    def _resume_conversation(self, conversation_id: int) -> None:
        """Pick an old conversation back up where it stopped."""
        conversation = self.history.conversation(conversation_id)
        if conversation is None or not conversation.sdk_session_id:
            return
        # Checked first: without a login the panel never opens, and resuming
        # anyway would swap the live conversation for one nobody can see.
        if not self.config.claude.enabled or not self._check_auth_once():
            return
        self.claude.resume(conversation.sdk_session_id)
        self._conversation_id = conversation_id
        self._open_ask(
            None,
            context=self.history.export_markdown(conversation_id),
            status="Discussion reprise",
        )

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
        self._answer_buffer = ""
        if self.config.history.enabled:
            if self._conversation_id is None:
                self._conversation_id = self.history.start("question")
            self.history.add_message(
                self._conversation_id, "user", question, _capture_info(capture)
            )
        self.ui.answer_started()
        self.claude.ask(question, capture)

    def _on_claude_chunk(self, text: str) -> None:
        self._answer_buffer += text
        self.ui.answer_chunk(text)

    def _on_claude_activity(self, line: str) -> None:
        self.ui.answer_status(line)

    def _on_claude_finished(self, status: str) -> None:
        self._record_answer("assistant", self._answer_buffer)
        self.ui.answer_finished(status)

    def _on_claude_reset(self) -> None:
        self._answer_buffer = ""
        self.ui.answer_reset()

    def _on_claude_failed(self, message: str) -> None:
        self._record_answer("error", message)
        self.ui.answer_failed(message)
        self.notify("Claude", message, kind="warning")

    # -- approvals --------------------------------------------------------

    def _on_claude_connection(self, state: str, detail: str) -> None:
        """Reflect the link to Claude, without nagging about it.

        Losing the connection is shown on the character and in the tray
        tooltip. Only a problem the user can actually act on — a missing
        login — is worth a notification, and only once.
        """
        self.ui.set_connection(state, detail)
        if state == OFFLINE and detail and detail not in self._reported_offline:
            self._reported_offline.add(detail)
            self.notify("Claude", detail, kind="warning")

    def _on_permission_requested(self, request_id: int, request) -> None:
        self._approval_queue.append((self.claude, request_id, request))
        self._show_next_approval()

    def _show_next_approval(self) -> None:
        if self._approval_current is not None or not self._approval_queue:
            return

        # Each entry carries its owner: the main session, an agent's session,
        # or the hook bridge. They number their requests independently, so
        # an id alone does not say who is waiting for the answer.
        owner, request_id, request = self._approval_queue.popleft()
        self._approval_current = request_id
        self._approval_owner = owner
        self._approval_request = request
        self.ui.ask_approval(request, self.config.claude.permission_timeout_seconds)

    def _on_approval_decided(self, decision: str) -> None:
        request_id, self._approval_current = self._approval_current, None
        if request_id is None:
            self._show_next_approval()
            return

        owner, self._approval_owner = self._approval_owner, None
        if owner == "bridge":
            # "always" has no equivalent in the hook protocol: allow once, and
            # remember the rule on our side for the next identical request.
            self.bridge.answer(request_id, "allow" if decision != "deny" else "deny")
        elif owner is not self.claude and owner is not None:
            owner.answer_permission(request_id, decision)
        else:
            self.claude.answer_permission(request_id, decision)
            # Only our own sessions go in our history; external ones have
            # their own transcript in Claude Code.
            request = self._approval_request
            if (
                self.config.history.enabled
                and self._conversation_id is not None
                and request is not None
            ):
                self.history.record_tool(
                    self._conversation_id, request.tool, request.detail, decision
                )
        self._approval_request = None
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
        self.sessions.record(event.session_id, event.project, "waiting", describe(event))
        self._approval_queue.append(
            (
                "bridge",
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
        if not self.ui.confirm_hooks(plan, installing):
            return
        self._apply_hooks(plan)

    def _apply_hooks(self, plan) -> bool:
        """Write a plan the user has seen and accepted. False if it failed."""
        if not plan.changed:
            return True
        try:
            saved = hooks_installer.apply(plan)
        except OSError as exc:
            self.notify("Hooks", f"Écriture impossible : {exc}", kind="warning")
            return False

        installed = hooks_installer.is_installed()
        self.ui.set_flags(hooks_installed=installed)
        self.notify(
            "Hooks installés" if installed else "Hooks retirés",
            hooks_installer.summarise_backup(saved),
        )
        if not installed:
            self.sessions.clear()
        return True

    def _open_quick_note(self) -> None:
        self.ui.open_window("quick_note")

    def _open_reminder(self) -> None:
        self.ui.open_window("reminder")

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

    # -- on-screen guidance -----------------------------------------------

    def _grab_escape(self, active: bool) -> None:
        """Claim Escape only while something is on screen.

        The overlay is click-through, so it can never have keyboard focus;
        a global hotkey is the only way Escape reaches it. Holding Escape
        any longer than that would steal it from every other app.
        """
        if active and self._escape_id is None:
            self._escape_id = self.hotkeys.grab("escape", self.ui.on_escape)
        elif not active and self._escape_id is not None:
            self.hotkeys.release(self._escape_id)
            self._escape_id = None

    def _open_settings(self) -> None:
        self.ui.open_window("settings")

    def _open_palette(self) -> None:
        """One field over everything: actions, launchers, notes, clipboard."""
        self.ui.open_window("palette")

    def _launch(self, entry) -> None:
        try:
            launch(entry)
        except LaunchError as exc:
            self.notify(f"Impossible de lancer {entry.label}", str(exc), kind="warning")

    def _toggle_avatar(self) -> None:
        self.ui.toggle_avatar()

    def _set_autostart(self, enabled: bool) -> None:
        winapi.set_autostart(enabled)
        actual = winapi.autostart_enabled()
        self.ui.set_flags(autostart=actual)
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

        self.ui.apply_config(self.config)
        self._apply_memory()
        self.monitor.apply_settings(self.config.monitor)
        self.clipboard.apply_settings(self.config.clipboard)

        # Hotkeys must be dropped and re-registered: Win32 has no "rebind".
        self.hotkeys.unregister_all()
        self._bind_hotkeys()

        self._report_startup_problems(reloaded=True)

    def notify(self, title: str, body: str = "", kind: str = "info") -> None:
        """One way to tell the user something, themed and in our control."""
        self.ui.notify(title, body, kind)

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
            self.notify("Configuration rechargée", "Tous les réglages ont été appliqués.")

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
    """Start the core, for the Tauri UI that launched it.

    `--headless` is still accepted (the Tauri supervisor passes it, and it
    was the only way to get this mode before the Qt windows went); it is now
    the only mode. `--exit-on-stdin-close`: quit when the launcher goes.
    """
    from .presenter_remote import ParentWatch, ProtocolPresenter, take_token

    args = list(argv if argv is not None else sys.argv)
    token, generated = take_token()
    presenter = ProtocolPresenter(token, announce_token=generated)
    watch = ParentWatch() if "--exit-on-stdin-close" in args[1:] else None
    args = [a for a in args if a not in ("--headless", "--exit-on-stdin-close")]
    app = AvatarApp(args, presenter)
    if watch is not None:
        watch.gone.connect(app.shutdown)
        watch.start()
    return app.run()


def _capture_info(capture) -> CaptureInfo | None:
    """A capture as the history keeps it: metadata and a small thumbnail.

    Never the full image. A history of screenshots is a history of whatever
    was on screen; 256 px is enough to recognise the conversation.
    """
    if capture is None:
        return None
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt

    small = capture.image.scaled(
        256,
        256,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    buffer = QBuffer()
    buffer.setData(QByteArray())
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    small.save(buffer, "PNG")
    return CaptureInfo(
        capture.kind.value,
        capture.label,
        capture.width,
        capture.height,
        bytes(buffer.data()),
    )


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
