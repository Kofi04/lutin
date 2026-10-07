"""The requests the Tauri app window makes: what each one reads, writes, refuses."""

from __future__ import annotations

import pytest

from wizard import services
from wizard.config import Config, LauncherEntry, load_config
from wizard.features.timers import TimerManager
from wizard.history import HistoryStore
from wizard.onboarding import Check, already_shown
from wizard.paths import config_path
from wizard.rpc import Rpc, RpcError
from wizard.storage import Storage


class FakeClipboard:
    def __init__(self) -> None:
        self.copied: list[str] = []

    def copy_to_clipboard(self, text: str) -> None:
        self.copied.append(text)


class FakeApp:
    """The parts of AvatarApp the services touch, with every call recorded."""

    def __init__(self, tmp_path) -> None:
        self.config = Config()
        self.storage = Storage(tmp_path / "wizard.sqlite3")
        self.history = HistoryStore(self.storage.connection)
        self.timers = TimerManager()
        self.clipboard = FakeClipboard()
        self.calls: list[tuple] = []
        self.auth_ok = True
        self.apply_ok = True

    def reload_config(self) -> None:
        self.config = load_config()
        self.calls.append(("reload",))

    def _copy_clip_image(self, clip_id: int) -> None:
        self.calls.append(("image", clip_id))

    def _launch(self, entry) -> None:
        self.calls.append(("launch", entry.label))

    def _resume_conversation(self, conversation_id: int) -> None:
        self.calls.append(("resume", conversation_id))

    def _launch_agent(self, task: str, folder: str) -> None:
        self.calls.append(("agent", task, folder))

    def _check_auth_once(self) -> bool:
        return self.auth_ok

    def _apply_hooks(self, plan) -> bool:
        self.calls.append(("hooks", plan.changed))
        return self.apply_ok

    def _setup_checks(self) -> list[Check]:
        return [Check("Claude Code", False, "Lancez <code>claude auth login</code>.")]

    def _set_reminder(self, seconds: int, label: str) -> None:
        self.calls.append(("reminder", seconds, label))

    def _set_autostart(self, enabled: bool) -> None:
        self.calls.append(("autostart", enabled))

    def _open_config_folder(self) -> None:
        self.calls.append(("folder",))


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Every path (config.toml, memory.md, state.ini) under the test's own folder.
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config_path().parent.mkdir(parents=True)
    fake = FakeApp(tmp_path)
    yield fake
    fake.storage.close()


@pytest.fixture
def rpc(app) -> Rpc:
    registry = Rpc()
    services.register(registry, app)
    return registry


def refused(rpc: Rpc, method: str, params: dict) -> RpcError:
    with pytest.raises(RpcError) as caught:
        rpc.call(method, params)
    return caught.value


# -- settings --------------------------------------------------------------


def test_settings_read_lists_every_field_with_its_value(rpc):
    data = rpc.call("settings.read", {})
    by_name = {f"{f['section']}.{f['key']}": f for f in data["fields"]}
    assert by_name["appearance.scale"]["value"] == Config().appearance.scale
    assert by_name["appearance.scale"]["minimum"] == 0.5
    assert by_name["hotkeys.quick_note"]["kind"] == "hotkey"
    # No memory file yet: the template, said to be one.
    assert data["memory"]["from_file"] is False
    assert data["memory"]["text"] == data["memory"]["template"]


def test_settings_write_changes_only_what_changed_and_reloads(rpc, app):
    config_path().write_text("[appearance]\nscale = 1.0\n", encoding="utf-8")
    result = rpc.call(
        "settings.write",
        {
            "values": {
                "appearance.scale": 2.5,
                "appearance.opacity": Config().appearance.opacity,
            }
        },
    )
    assert result == {"written": 1}
    assert "scale = 2.5" in config_path().read_text(encoding="utf-8")
    assert app.config.appearance.scale == 2.5
    assert ("reload",) in app.calls


def test_settings_write_refuses_out_of_range_and_writes_nothing(rpc):
    config_path().write_text("[appearance]\nscale = 1.0\n", encoding="utf-8")
    error = refused(rpc, "settings.write", {"values": {"appearance.scale": 9}})
    assert error.code == "invalid"
    assert "entre 0.5 et 4" in error.message
    assert "scale = 1.0" in config_path().read_text(encoding="utf-8")


def test_settings_write_refuses_unknown_settings(rpc):
    error = refused(rpc, "settings.write", {"values": {"claude.model": "x"}})
    assert "Réglage inconnu" in error.message


def test_settings_write_refuses_two_actions_on_one_shortcut(rpc):
    same = Config().hotkeys.quick_note
    error = refused(rpc, "settings.write", {"values": {"hotkeys.clipboard": same}})
    assert error.code == "invalid"
    assert "utilisent tous deux" in error.message


def test_check_hotkeys_reports_conflicts_and_unknown_keys(rpc):
    problems = rpc.call(
        "settings.check_hotkeys",
        {
            "bindings": {
                "quick_note": "ctrl+alt+N",
                "clipboard": "ctrl+alt+N",
                "launcher": "ctrl+nope",
            }
        },
    )["problems"]
    assert any("Note rapide" in p and "Presse-papiers" in p for p in problems)
    assert any("Palette de commandes" in p and "pas reconnu" in p for p in problems)


def test_settings_write_saves_the_memory(rpc):
    rpc.call("settings.write", {"values": {}, "memory": "Je m'appelle Tim."})
    data = rpc.call("settings.read", {})
    assert data["memory"] == {
        **data["memory"],
        "text": "Je m'appelle Tim.",
        "from_file": True,
    }


# -- clipboard and notes -----------------------------------------------------


def test_clips_list_search_copy_delete(rpc, app):
    first = app.storage.add_clip("bonjour le monde")
    app.storage.add_clip("autre chose")
    items = rpc.call("clips.list", {"search": "bonjour"})["items"]
    assert [i["id"] for i in items] == [first]
    assert items[0]["kind"] == "text" and items[0]["thumbnail"] is None

    assert rpc.call("clips.copy", {"id": first}) == {"copied": "text"}
    assert app.clipboard.copied == ["bonjour le monde"]

    rpc.call("clips.delete", {"id": first})
    assert refused(rpc, "clips.copy", {"id": first}).code == "not_found"


def test_image_clips_copy_the_picture_not_the_label(rpc, app):
    clip_id = app.storage.add_image_clip(b"png", b"thumb", 2, 2)
    item = rpc.call("clips.list", {})["items"][0]
    assert item["kind"] == "image" and item["thumbnail"]
    assert rpc.call("clips.copy", {"id": clip_id}) == {"copied": "image"}
    assert ("image", clip_id) in app.calls
    assert app.clipboard.copied == []


def test_notes_add_refuses_empty(rpc):
    assert refused(rpc, "notes.add", {"body": "   "}).code == "invalid"


def test_notes_add_list_copy_delete(rpc, app):
    note_id = rpc.call("notes.add", {"body": "  acheter du pain "})["id"]
    assert rpc.call("notes.list", {})["items"][0]["body"] == "acheter du pain"
    rpc.call("notes.copy", {"id": note_id})
    assert app.clipboard.copied == ["acheter du pain"]
    rpc.call("notes.delete", {"id": note_id})
    assert rpc.call("notes.list", {})["items"] == []


# -- reminders and launcher ----------------------------------------------------


def test_timers_add_by_text_list_and_cancel(rpc):
    added = rpc.call("timers.add", {"label": "Thé", "duration": "1h30"})
    items = rpc.call("timers.list", {})["items"]
    assert items == [
        {
            "id": added["id"],
            "label": "Thé",
            "remaining": 5400,
            "total": 5400,
            "remaining_text": "1:30:00",
        }
    ]
    rpc.call("timers.cancel", {"id": added["id"]})
    assert rpc.call("timers.list", {})["items"] == []


def test_timers_add_refuses_unreadable_duration(rpc):
    error = refused(rpc, "timers.add", {"duration": "bientôt"})
    assert error.message.startswith("Durée non reconnue")


def test_timers_cancel_all(rpc):
    rpc.call("timers.add", {"seconds": 60})
    rpc.call("timers.add", {"seconds": 120})
    rpc.call("timers.cancel_all", {})
    assert rpc.call("timers.list", {})["items"] == []


def test_launcher_runs_by_index_and_refuses_stale_ones(rpc, app):
    app.config.launcher = [LauncherEntry("Notes", "notepad.exe")]
    assert rpc.call("launcher.list", {})["items"][0]["label"] == "Notes"
    rpc.call("launcher.run", {"index": 0})
    assert ("launch", "Notes") in app.calls
    assert refused(rpc, "launcher.run", {"index": 3}).code == "not_found"


# -- history -------------------------------------------------------------------


def test_history_groups_search_get_and_edit(rpc, app):
    talk = app.history.start("question", title="Pourquoi le ciel est bleu")
    app.history.add_message(talk, "user", "Pourquoi le ciel est bleu ?")
    app.history.add_message(talk, "assistant", "La diffusion de Rayleigh.")

    groups = rpc.call("history.list", {})["groups"]
    assert groups[0]["items"][0]["id"] == talk
    assert groups[0]["items"][0]["resumable"] is False

    hits = rpc.call("history.list", {"search": "Rayleigh"})
    assert hits["mode"] == "search" and hits["items"][0]["id"] == talk

    assert "Rayleigh" in rpc.call("history.get", {"id": talk})["markdown"]

    rpc.call("history.rename", {"id": talk, "title": "Le ciel"})
    rpc.call("history.pin", {"id": talk, "pinned": True})
    got = rpc.call("history.get", {"id": talk})["conversation"]
    assert got["title"] == "Le ciel" and got["pinned"] is True

    assert refused(rpc, "history.rename", {"id": talk, "title": " "}).code == "invalid"


def test_history_resume_needs_an_answer_from_claude(rpc, app):
    talk = app.history.start("question", title="Sans réponse")
    assert refused(rpc, "history.resume", {"id": talk}).code == "invalid"
    app.history.set_session(talk, "sdk-123")
    rpc.call("history.resume", {"id": talk})
    assert ("resume", talk) in app.calls


def test_history_delete_and_missing(rpc, app):
    talk = app.history.start("question", title="Éphémère")
    rpc.call("history.delete", {"id": talk})
    assert refused(rpc, "history.get", {"id": talk}).code == "not_found"


# -- hooks, onboarding, agents ---------------------------------------------------


def test_hooks_apply_writes_only_what_the_user_saw(rpc, app, monkeypatch, tmp_path):
    from wizard.bridge import installer

    settings = tmp_path / "settings.json"
    real = installer.plan_install
    monkeypatch.setattr(installer, "plan_install", lambda: real(settings))
    seen = rpc.call("hooks.plan", {"install": True})["diff"]

    # settings.json edited in the meantime: the diff shown is no longer true.
    settings.write_text('{"theme": "dark"}', encoding="utf-8")
    assert refused(rpc, "hooks.apply", {"install": True, "seen": seen}).code == "stale"
    assert app.calls == []

    seen = rpc.call("hooks.plan", {"install": True})["diff"]
    rpc.call("hooks.apply", {"install": True, "seen": seen})
    assert app.calls == [("hooks", True)]

    app.apply_ok = False
    error = refused(rpc, "hooks.apply", {"install": True, "seen": seen})
    assert error.code == "write_failed"


def test_onboarding_sends_markdown_never_html(rpc):
    info = rpc.call("onboarding.info", {})
    assert info["checks"][0]["detail"] == "Lancez `claude auth login`."
    assert info["shortcuts"][0]["label"] == "Demander à Claude"


def test_onboarding_done_is_remembered(rpc):
    rpc.call("onboarding.done", {})
    assert already_shown()


def test_agent_launch_checks_task_and_folder(rpc, app, tmp_path):
    assert refused(
        rpc, "agents.launch", {"task": "", "folder": str(tmp_path)}
    ).message == ("Décrivez la tâche.")
    missing = str(tmp_path / "nope")
    assert refused(rpc, "agents.launch", {"task": "x", "folder": missing}).message == (
        "Choisissez un dossier qui existe."
    )
    app.auth_ok = False
    assert (
        "claude auth login"
        in refused(rpc, "agents.launch", {"task": "x", "folder": str(tmp_path)}).message
    )


def test_agent_launch_remembers_the_folder(rpc, app, tmp_path):
    assert rpc.call("agents.last_folder", {}) == {"folder": ""}
    rpc.call("agents.launch", {"task": "fais passer les tests", "folder": str(tmp_path)})
    assert ("agent", "fais passer les tests", str(tmp_path)) in app.calls
    assert rpc.call("agents.last_folder", {}) == {"folder": str(tmp_path)}


def test_history_export_writes_the_markdown(rpc, app, tmp_path):
    talk = app.history.start("question", title="À garder")
    app.history.add_message(talk, "user", "Bonjour")
    target = tmp_path / "out.md"
    rpc.call("history.export", {"id": talk, "path": str(target)})
    assert "Bonjour" in target.read_text(encoding="utf-8")
    missing = tmp_path / "nope" / "out.md"
    assert refused(rpc, "history.export", {"id": talk, "path": str(missing)}).code == (
        "write_failed"
    )


def test_a_reminder_in_plain_words(rpc, app):
    found = rpc.call("timers.parse", {"text": "rappel dans 20 min sortir le pain"})[
        "reminder"
    ]
    assert found["seconds"] == 1200
    assert "pain" in found["label"]
    assert rpc.call("timers.parse", {"text": "bonjour"}) == {"reminder": None}
    rpc.call("timers.set", {"seconds": 1200, "label": found["label"]})
    assert app.calls[-1] == ("reminder", 1200, found["label"])
