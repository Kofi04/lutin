"""Migrations and the conversation history."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from wizard.history import (
    CaptureInfo,
    HistoryStore,
    fts_query,
    group_by_date,
    title_from,
)
from wizard.schema import LATEST, SchemaTooNew, migrate, version_of
from wizard.storage import Storage


@pytest.fixture
def storage(tmp_path):
    with Storage(tmp_path / "wizard.db") as store:
        yield store


@pytest.fixture
def history(storage):
    return HistoryStore(storage.connection)


# -- migrations -------------------------------------------------------------


def test_a_fresh_database_lands_on_the_latest_version(storage):
    assert version_of(storage.connection) == LATEST
    assert storage.migrated == list(range(1, LATEST + 1))


def test_reopening_applies_nothing(tmp_path):
    Storage(tmp_path / "db").close()
    with Storage(tmp_path / "db") as again:
        assert again.migrated == []


def test_a_pre_versioning_database_keeps_its_rows(tmp_path):
    # Exactly what every existing user has: the old tables, user_version 0.
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL,"
        " created_at TEXT NOT NULL);"
        "CREATE TABLE clips (id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL,"
        " created_at TEXT NOT NULL);"
        "INSERT INTO notes (body, created_at) VALUES ('garde-moi', '2026-01-01');"
        "INSERT INTO clips (body, created_at) VALUES ('copie', '2026-01-01');"
    )
    conn.close()

    with Storage(path) as store:
        assert [r.body for r in store.list_notes()] == ["garde-moi"]
        assert [r.body for r in store.list_clips()] == ["copie"]
        assert version_of(store.connection) == LATEST
        # And the new clip columns exist, with a sane default for old rows.
        kind = store.connection.execute("SELECT kind FROM clips").fetchone()[0]
        assert kind == "text"


def test_a_newer_database_is_refused_not_touched(tmp_path):
    path = tmp_path / "future.db"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {LATEST + 1}")
    conn.commit()
    conn.close()

    with pytest.raises(SchemaTooNew):
        Storage(path)


def test_a_failing_step_leaves_nothing_half_applied(monkeypatch):
    from wizard import schema

    conn = sqlite3.connect(":memory:")
    broken = (*schema.MIGRATIONS[:1], "CREATE TABLE half (x);\nTHIS IS NOT SQL;")
    monkeypatch.setattr(schema, "MIGRATIONS", broken)
    monkeypatch.setattr(schema, "LATEST", 2)

    with pytest.raises(sqlite3.Error):
        schema.migrate(conn)

    assert version_of(conn) == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "half" not in tables
    assert not conn.in_transaction


def test_migrating_is_idempotent_on_an_open_connection(storage):
    assert migrate(storage.connection) == []


# -- writing and reading ----------------------------------------------------


def test_the_first_question_names_the_conversation(history):
    cid = history.start()
    history.add_message(cid, "user", "Pourquoi ma boucle modifie-t-elle la liste ?")
    history.add_message(cid, "assistant", "Parce que…")

    assert (
        history.conversation(cid).title == "Pourquoi ma boucle modifie-t-elle la liste ?"
    )


def test_a_long_first_question_is_shortened():
    assert len(title_from("mot " * 100)) <= 60
    assert title_from("mot " * 100).endswith("…")


def test_an_explicit_title_is_not_overwritten(history):
    cid = history.start(title="Mon sujet")
    history.add_message(cid, "user", "autre chose")

    assert history.conversation(cid).title == "Mon sujet"


def test_messages_come_back_in_order_with_their_captures(history):
    cid = history.start()
    thumb = b"\x89PNG fake"
    history.add_message(
        cid, "user", "Et ça ?", CaptureInfo("region", "Zone 640×320", 640, 320, thumb)
    )
    history.add_message(cid, "assistant", "C'est un bouton.")

    messages = history.messages(cid)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].captures[0].label == "Zone 640×320"
    assert messages[0].captures[0].thumbnail == thumb


def test_the_session_id_is_kept_for_resuming(history):
    cid = history.start()
    history.set_session(cid, "abc-123")

    assert history.conversation(cid).sdk_session_id == "abc-123"


def test_tool_decisions_are_recorded(history):
    cid = history.start()
    history.record_tool(cid, "Bash", "pytest -q", "allow")

    assert [(c.tool, c.decision) for c in history.tool_calls(cid)] == [("Bash", "allow")]


# -- listing ----------------------------------------------------------------


def test_pinned_conversations_come_first(history):
    old = history.start(title="ancienne")
    history.start(title="récente")
    history.pin(old)

    assert [c.title for c in history.conversations()][0] == "ancienne"


def test_filtering_by_kind(history):
    history.start("question", "q")
    history.start("agent", "a")

    assert [c.title for c in history.conversations(kind="agent")] == ["a"]


def test_rename(history):
    cid = history.start(title="avant")
    history.rename(cid, "  après  ")

    assert history.conversation(cid).title == "après"


def test_deleting_a_conversation_takes_everything_with_it(history, storage):
    cid = history.start()
    history.add_message(cid, "user", "secret", CaptureInfo("region", "Zone", 1, 1, b"x"))
    history.record_tool(cid, "Bash", "ls", "deny")
    history.delete(cid)

    conn = storage.connection
    for table in ("messages", "captures", "tool_calls"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    # And the search index forgot it too.
    assert history.search("secret") == []


# -- search -----------------------------------------------------------------


def test_search_ignores_accents(history):
    cid = history.start()
    history.add_message(cid, "user", "Compte rendu de la réunion d'équipe")

    assert [h.conversation.id for h in history.search("reunion")] == [cid]
    assert [h.conversation.id for h in history.search("EQUIPE")] == [cid]


def test_search_matches_word_prefixes(history):
    cid = history.start()
    history.add_message(cid, "assistant", "La configuration est invalide")

    assert history.search("config")[0].conversation.id == cid


def test_search_requires_every_word(history):
    a = history.start()
    history.add_message(a, "user", "budget réunion")
    b = history.start()
    history.add_message(b, "user", "budget vacances")

    assert [h.conversation.id for h in history.search("budget réunion")] == [a]


@pytest.mark.parametrize(
    "nasty", ['"', "a OR b", "NOT", "-x", "col:val", "(", "*", "'; DROP"]
)
def test_query_syntax_cannot_escape_or_crash(history, nasty):
    cid = history.start()
    history.add_message(cid, "user", "rien à voir")

    history.search(nasty)  # must not raise


def test_fts_query_quotes_every_word():
    assert fts_query('dis "bonjour" OR') == '"dis"* "bonjour"* "OR"*'
    assert fts_query("  !!  ") is None


def test_one_hit_per_conversation_with_a_snippet(history):
    cid = history.start()
    history.add_message(cid, "user", "python partout")
    history.add_message(cid, "assistant", "encore python")

    hits = history.search("python")
    assert len(hits) == 1
    assert "[" in hits[0].snippet


def test_a_title_match_is_found_without_a_message_match(history):
    cid = history.start(title="Projet Koffi")

    assert [h.conversation.id for h in history.search("koffi")] == [cid]


# -- retention --------------------------------------------------------------


def _age(storage, cid, days):
    stamp = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
    storage.connection.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?", (stamp, cid)
    )
    storage.connection.commit()


def test_retention_drops_old_unpinned_conversations(history, storage):
    old, pinned_old, fresh = history.start(), history.start(), history.start()
    for cid in (old, pinned_old):
        _age(storage, cid, 100)
    history.pin(pinned_old)

    assert history.purge_older_than(90) == 1
    remaining = {c.id for c in history.conversations()}
    assert remaining == {pinned_old, fresh}


def test_retention_zero_keeps_everything(history, storage):
    cid = history.start()
    _age(storage, cid, 10_000)

    assert history.purge_older_than(0) == 0


def test_clear_removes_everything_including_pinned(history):
    history.pin(history.start())
    history.start()

    assert history.clear() == 2
    assert history.conversations() == []


# -- export -----------------------------------------------------------------


def test_markdown_export(history):
    cid = history.start()
    history.add_message(
        cid, "user", "Question ?", CaptureInfo("window", "Chrome", 800, 600)
    )
    history.add_message(cid, "assistant", "Réponse.")
    history.record_tool(cid, "Edit", "app.py", "allow")

    text = history.export_markdown(cid)
    assert text.startswith("# Question ?")
    assert "## Vous" in text and "## Claude" in text
    assert "Capture : Chrome (800×600)" in text
    assert "`Edit` — allow" in text


def test_exporting_a_missing_conversation_is_empty(history):
    assert history.export_markdown(999) == ""


# -- grouping by date ------------------------------------------------------


def _conv(history, storage, days_ago, pinned=False):
    cid = history.start(title=f"{days_ago}")
    _age(storage, cid, days_ago)
    if pinned:
        history.pin(cid)
    return history.conversation(cid)


def test_grouping_by_local_day(history, storage):
    items = [
        _conv(history, storage, 0),
        _conv(history, storage, 1),
        _conv(history, storage, 4),
        _conv(history, storage, 20),
        _conv(history, storage, 200),
        _conv(history, storage, 300, pinned=True),
    ]
    labels = [label for label, _ in group_by_date(items)]

    assert labels == [
        "Épinglées",
        "Aujourd'hui",
        "Hier",
        "Cette semaine",
        "Ce mois-ci",
        "Plus ancien",
    ]


def test_empty_groups_are_left_out(history, storage):
    labels = [label for label, _ in group_by_date([_conv(history, storage, 0)])]

    assert labels == ["Aujourd'hui"]
