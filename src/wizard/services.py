"""The requests the Tauri app window may make (rpc.py), one per action.

Each one is the Qt window's own action, moved behind a method name: the same
core function, the same French messages, the same checks. Nothing a window
sends is trusted: values are checked against settings_schema, ids are looked
up, a hooks change is planned again here rather than taken from the window.
"""

from __future__ import annotations

import base64
import os
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSettings

from . import claude_transcripts, hotkey_spec, onboarding, settings_schema, winapi
from .assistant import memory as user_memory
from .bridge import installer as hooks_installer
from .config import load_config
from .config_writer import ConfigWriteError, Edit, write_edits
from .features.timers import parse_duration
from .history import KINDS, group_by_date
from .paths import config_path, state_path
from .rpc import Rpc, RpcError

if TYPE_CHECKING:
    from .app import AvatarApp


#: Shared with the Qt dialog (ui_agent.py) while both exist.
_LAST_FOLDER = "agents/last_folder"


def _state() -> QSettings:
    return QSettings(str(state_path()), QSettings.Format.IniFormat)


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _b64(data: bytes | None) -> str | None:
    return base64.b64encode(data).decode("ascii") if data else None


def _markdown(html: str) -> str:
    """The onboarding's little bits of HTML as Markdown: never sent as HTML."""
    text = re.sub(r"</?code>", "`", html)
    text = re.sub(r"</?b>", "**", text)
    return re.sub(r"<[^>]+>", "", text)


def _record(record) -> dict:
    return {
        "id": record.id,
        "body": record.body,
        "created_at": _iso(record.created_at),
        "kind": record.kind,
        "thumbnail": _b64(record.thumbnail),
    }


def _conversation(conversation) -> dict:
    return {
        "id": conversation.id,
        "kind": conversation.kind,
        "kind_label": KINDS.get(conversation.kind, conversation.kind),
        "title": conversation.title or "Sans titre",
        "updated_at": _iso(conversation.updated_at),
        "pinned": conversation.pinned,
        "project": conversation.project,
        # Nothing to resume if Claude never answered (the Qt window said so).
        "resumable": bool(conversation.sdk_session_id),
    }


def register(rpc: Rpc, app: AvatarApp) -> None:
    """Every method, bound to this app."""
    storage, history, timers = app.storage, app.history, app.timers

    def method(name: str):
        def wrap(fn):
            rpc.register(name, fn)
            return fn

        return wrap

    # -- settings --------------------------------------------------------

    def current(section: str, key: str):
        return getattr(getattr(app.config, section), key)

    @method("settings.read")
    def settings_read(params: dict) -> dict:
        app.config = load_config()  # hand edits picked up, as the Qt window did
        text = user_memory.load_memory()
        return {
            "fields": [
                {**f.describe(), "value": current(f.section, f.key)}
                for f in settings_schema.FIELDS
            ],
            "memory": {
                "text": text or user_memory.TEMPLATE,
                "from_file": bool(text),
                "template": user_memory.TEMPLATE,
                "limit": user_memory.MAX_MEMORY,
            },
        }

    @method("settings.memory_size")
    def memory_size(params: dict) -> dict:
        text = str(params["text"])
        return {
            "sent": len(user_memory.for_prompt(text)),
            "truncated": user_memory.is_truncated(text),
        }

    def hotkey_problems(bindings: dict[str, str]) -> list[str]:
        labels = settings_schema.HOTKEY_LABELS
        problems = [
            f"« {labels.get(c.first, c.first)} » et « {labels.get(c.second, c.second)} »"
            f" utilisent tous deux {c.spec}."
            for c in hotkey_spec.find_conflicts(bindings)
        ]
        problems += [
            f"Le raccourci de « {labels.get(action, action)} » n'est pas reconnu."
            for action in hotkey_spec.invalid_bindings(bindings)
        ]
        return problems

    @method("settings.check_hotkeys")
    def check_hotkeys(params: dict) -> dict:
        return {"problems": hotkey_problems(dict(params["bindings"]))}

    @method("settings.write")
    def settings_write(params: dict) -> dict:
        values: dict[str, Any] = params.get("values", {})
        edits: list[Edit] = []
        try:
            for name, value in values.items():
                section, key = name.split(".", 1)
                value = settings_schema.check(section, key, value)
                if value != current(section, key):
                    edits.append(Edit(section, key, value))
        except settings_schema.SettingError as exc:
            raise RpcError("invalid", str(exc)) from exc

        bindings = {
            f.key: (values.get(f"hotkeys.{f.key}") or current("hotkeys", f.key))
            for f in settings_schema.FIELDS
            if f.kind == "hotkey"
        }
        problems = hotkey_problems(bindings)
        if problems:
            raise RpcError("invalid", "\n".join(problems))

        # Memory first, as the Qt window did: it is the part you typed.
        memory_text = params.get("memory")
        if memory_text is not None:
            try:
                user_memory.save_memory(str(memory_text))
            except OSError as exc:
                raise RpcError(
                    "write_failed", f"Impossible d'enregistrer la mémoire : {exc}"
                ) from exc
        if edits:
            try:
                write_edits(config_path(), edits)
            except (OSError, ValueError, ConfigWriteError) as exc:
                raise RpcError(
                    "write_failed", f"Impossible d'enregistrer : {exc}"
                ) from exc
        # Reloading is what makes it take effect, hotkeys included.
        app.reload_config()
        return {"written": len(edits)}

    # -- clipboard and notes ---------------------------------------------

    def search_term(params: dict) -> str | None:
        return str(params.get("search") or "").strip() or None

    @method("clips.list")
    def clips_list(params: dict) -> dict:
        records = storage.list_clips(
            limit=int(params.get("limit", 200)), search=search_term(params)
        )
        return {"items": [_record(r) for r in records]}

    @method("clips.copy")
    def clips_copy(params: dict) -> dict:
        clip_id = int(params["id"])
        record = next(
            (r for r in storage.list_clips(limit=5000) if r.id == clip_id), None
        )
        if record is None:
            raise RpcError("not_found", "Cette entrée n'existe plus.")
        if record.kind == "image":
            # The picture, never its label: a quiet wrong answer otherwise.
            app._copy_clip_image(clip_id)
            return {"copied": "image"}
        app.clipboard.copy_to_clipboard(record.body)
        return {"copied": "text"}

    @method("clips.delete")
    def clips_delete(params: dict) -> dict:
        storage.delete_clip(int(params["id"]))
        return {}

    @method("notes.list")
    def notes_list(params: dict) -> dict:
        records = storage.list_notes(
            limit=int(params.get("limit", 200)), search=search_term(params)
        )
        return {"items": [_record(r) for r in records]}

    @method("notes.add")
    def notes_add(params: dict) -> dict:
        body = str(params["body"]).strip()
        if not body:
            raise RpcError("invalid", "Impossible d'enregistrer une note vide.")
        return {"id": storage.add_note(body)}

    @method("notes.copy")
    def notes_copy(params: dict) -> dict:
        note_id = int(params["id"])
        record = next(
            (r for r in storage.list_notes(limit=5000) if r.id == note_id), None
        )
        if record is None:
            raise RpcError("not_found", "Cette note n'existe plus.")
        app.clipboard.copy_to_clipboard(record.body)
        return {}

    @method("notes.delete")
    def notes_delete(params: dict) -> dict:
        storage.delete_note(int(params["id"]))
        return {}

    # -- reminders -------------------------------------------------------

    @method("timers.list")
    def timers_list(params: dict) -> dict:
        return {
            "items": [
                {
                    "id": r.id,
                    "label": r.label,
                    "remaining": r.remaining,
                    "total": r.total_seconds,
                    "remaining_text": r.remaining_text,
                }
                for r in timers.active
            ]
        }

    @method("timers.add")
    def timers_add(params: dict) -> dict:
        if "seconds" in params:
            seconds = int(params["seconds"])
        else:
            try:
                seconds = parse_duration(str(params.get("duration", "")))
            except ValueError as exc:
                raise RpcError(
                    "invalid",
                    "Durée non reconnue. Essayez par exemple 25, 25m, 1h30 ou 90s.",
                ) from exc
        reminder = timers.add(str(params.get("label", "")), seconds)
        return {"id": reminder.id, "label": reminder.label}

    @method("timers.cancel")
    def timers_cancel(params: dict) -> dict:
        timers.cancel(int(params["id"]))
        return {}

    @method("timers.cancel_all")
    def timers_cancel_all(params: dict) -> dict:
        timers.cancel_all()
        return {}

    # -- launcher ----------------------------------------------------------

    @method("launcher.list")
    def launcher_list(params: dict) -> dict:
        return {
            "items": [
                {"index": i, "label": e.label, "target": e.target}
                for i, e in enumerate(app.config.launcher)
            ]
        }

    @method("launcher.run")
    def launcher_run(params: dict) -> dict:
        index = int(params["index"])
        if not 0 <= index < len(app.config.launcher):
            raise RpcError("not_found", "Cette entrée n'existe plus dans config.toml.")
        app._launch(app.config.launcher[index])
        return {}

    # -- history -----------------------------------------------------------

    @method("history.list")
    def history_list(params: dict) -> dict:
        kind = str(params.get("kind") or "") or None
        text = search_term(params)
        if text:
            hits = history.search(text, kind=kind)
            return {
                "mode": "search",
                "items": [
                    {**_conversation(h.conversation), "snippet": h.snippet} for h in hits
                ],
            }
        groups = group_by_date(history.conversations(kind=kind))
        return {
            "mode": "groups",
            "groups": [
                {"title": title, "items": [_conversation(c) for c in items]}
                for title, items in groups
            ],
        }

    def conversation_or_fail(params: dict):
        conversation = history.conversation(int(params["id"]))
        if conversation is None:
            raise RpcError("not_found", "Cette discussion n'existe plus.")
        return conversation

    @method("history.get")
    def history_get(params: dict) -> dict:
        conversation = conversation_or_fail(params)
        return {
            "conversation": _conversation(conversation),
            "markdown": history.export_markdown(conversation.id),
        }

    @method("history.rename")
    def history_rename(params: dict) -> dict:
        title = str(params["title"]).strip()
        if not title:
            raise RpcError("invalid", "Le titre ne peut pas être vide.")
        history.rename(conversation_or_fail(params).id, title)
        return {}

    @method("history.pin")
    def history_pin(params: dict) -> dict:
        history.pin(conversation_or_fail(params).id, bool(params["pinned"]))
        return {}

    @method("history.delete")
    def history_delete(params: dict) -> dict:
        history.delete(conversation_or_fail(params).id)
        return {}

    @method("history.clear")
    def history_clear(params: dict) -> dict:
        return {"deleted": history.clear()}

    @method("history.resume")
    def history_resume(params: dict) -> dict:
        conversation = conversation_or_fail(params)
        if not conversation.sdk_session_id:
            raise RpcError(
                "invalid",
                "Cette discussion n'a jamais reçu de réponse : rien à reprendre.",
            )
        app._resume_conversation(conversation.id)
        return {}

    @method("history.export")
    def history_export(params: dict) -> dict:
        # The path comes from the window's native "save as": the user chose it.
        conversation = conversation_or_fail(params)
        target = Path(str(params["path"]))
        try:
            target.write_text(history.export_markdown(conversation.id), encoding="utf-8")
        except OSError as exc:
            raise RpcError("write_failed", f"Export impossible : {exc}") from exc
        return {"path": str(target)}

    @method("history.kinds")
    def history_kinds(params: dict) -> dict:
        return {"kinds": [{"value": k, "label": v} for k, v in KINDS.items()]}

    # -- Claude Code's own sessions (read-only) -------------------------------

    @method("transcripts.list")
    def transcripts_list(params: dict) -> dict:
        text = (search_term(params) or "").casefold()
        sessions = [
            s
            for s in claude_transcripts.list_sessions()
            if not text or text in s.title.casefold() or text in s.project.casefold()
        ]
        return {
            "items": [
                {
                    "session_id": s.session_id,
                    "title": s.title,
                    "project": s.project,
                    "modified": _iso(s.modified),
                }
                for s in sessions
            ]
        }

    @method("transcripts.get")
    def transcripts_get(params: dict) -> dict:
        wanted = str(params["session_id"])
        session = next(
            (s for s in claude_transcripts.list_sessions() if s.session_id == wanted),
            None,
        )
        if session is None:
            raise RpcError("not_found", "Cette session n'existe plus.")
        return {"markdown": claude_transcripts.as_markdown(session)}

    # -- hooks -------------------------------------------------------------

    def plan_for(params: dict):
        installing = bool(params["install"])
        plan = (
            hooks_installer.plan_install()
            if installing
            else hooks_installer.plan_uninstall()
        )
        return installing, plan

    @method("hooks.plan")
    def hooks_plan(params: dict) -> dict:
        installing, plan = plan_for(params)
        return {
            "installing": installing,
            "changed": plan.changed,
            "path": str(plan.path),
            "diff": plan.diff,
            "installed": hooks_installer.is_installed(),
            "stale": hooks_installer.is_stale(),
        }

    @method("hooks.apply")
    def hooks_apply(params: dict) -> dict:
        # Planned again here: what is written is what the core computes now,
        # never a diff a window sent. That diff only proves what the user saw:
        # if settings.json changed since, they approved something else.
        installing, plan = plan_for(params)
        if plan.diff != str(params["seen"]):
            raise RpcError(
                "stale",
                "settings.json a changé depuis l'affichage : relisez le changement.",
            )
        if not app._apply_hooks(plan):
            raise RpcError("write_failed", "L'écriture de settings.json a échoué.")
        return {"installed": hooks_installer.is_installed()}

    # -- onboarding ----------------------------------------------------------

    @method("onboarding.info")
    def onboarding_info(params: dict) -> dict:
        return {
            "checks": [
                {
                    "label": c.label,
                    "ok": c.ok,
                    "detail": _markdown(c.detail),
                    "action": c.action,
                }
                for c in app._setup_checks()
            ],
            "shortcuts": [
                {"label": label, "keys": onboarding.pretty(spec)}
                for label, spec in onboarding.shortcut_rows(app.config.hotkeys)
            ],
        }

    @method("onboarding.done")
    def onboarding_done(params: dict) -> dict:
        onboarding.mark_shown()
        return {}

    # -- agents --------------------------------------------------------------

    @method("agents.last_folder")
    def agents_last_folder(params: dict) -> dict:
        folder = str(_state().value(_LAST_FOLDER, "") or "")
        return {"folder": folder if folder and Path(folder).is_dir() else ""}

    @method("agents.launch")
    def agents_launch(params: dict) -> dict:
        task = str(params.get("task", "")).strip()
        folder = str(params.get("folder", "")).strip()
        if not task:
            raise RpcError("invalid", "Décrivez la tâche.")
        if not folder or not Path(folder).is_dir():
            raise RpcError("invalid", "Choisissez un dossier qui existe.")
        if not app.config.claude.enabled:
            raise RpcError("invalid", "Claude est désactivé dans les paramètres.")
        if not app._check_auth_once():
            raise RpcError(
                "invalid", "Claude Code n'est pas connecté : claude auth login."
            )
        store = _state()
        store.setValue(_LAST_FOLDER, folder)
        store.sync()
        app._launch_agent(task, folder)
        return {}

    # -- system ----------------------------------------------------------------

    @method("system.info")
    def system_info(params: dict) -> dict:
        return {
            "autostart": winapi.autostart_enabled(),
            "hooks_installed": hooks_installer.is_installed(),
            "hooks_stale": hooks_installer.is_stale(),
        }

    @method("system.autostart")
    def system_autostart(params: dict) -> dict:
        app._set_autostart(bool(params["enabled"]))
        return {"autostart": winapi.autostart_enabled()}

    @method("system.open_config")
    def system_open_config(params: dict) -> dict:
        if params.get("file"):
            path = config_path()
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except OSError as exc:
                raise RpcError(
                    "failed", f"Impossible d'ouvrir {path.name} : {exc}"
                ) from exc
        else:
            app._open_config_folder()
        return {}
