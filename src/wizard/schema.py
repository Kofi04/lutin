"""The database schema, as a ladder of numbered migrations.

Before this, the schema was a `CREATE TABLE IF NOT EXISTS` script run on every
start. That works exactly until a table needs a new column: on an existing
database the `CREATE` is skipped, the column never appears, and the first query
that uses it fails — on the user's machine, not on the developer's fresh one.

So the version lives in `PRAGMA user_version`, and each step below runs once, in
order, inside a transaction. Rules:

* **A migration is never edited once released.** Fixing one means adding the
  next. Editing step 2 would leave every database that already ran the old step
  2 on a schema nobody can reproduce.
* **A database newer than this code is refused, not touched.** Running old code
  against a newer schema is how data gets silently mangled; `SchemaTooNew`
  stops the app instead and says why.
* **Version 1 is the schema that existed before versioning**, written with
  `IF NOT EXISTS` so a pre-ladder database (user_version 0, tables present)
  adopts it without losing a row.
"""

from __future__ import annotations

import sqlite3


class SchemaTooNew(RuntimeError):
    """The database was written by a newer version of the app."""


_V1_NOTES_AND_CLIPS = """
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_created ON notes (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_clips_created ON clips (created_at DESC);
"""

_V2_HISTORY = """
CREATE TABLE conversations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL DEFAULT 'question',
    title           TEXT NOT NULL DEFAULT '',
    started_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    sdk_session_id  TEXT,
    project         TEXT NOT NULL DEFAULT '',
    pinned          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_conversations_updated ON conversations (updated_at DESC);

CREATE TABLE messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id  INTEGER NOT NULL
                     REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL,
    body             TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
CREATE INDEX idx_messages_conversation ON messages (conversation_id, id);

CREATE TABLE captures (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id       INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    kind             TEXT NOT NULL,
    label            TEXT NOT NULL,
    width            INTEGER NOT NULL,
    height           INTEGER NOT NULL,
    thumbnail        BLOB
);

CREATE TABLE tool_calls (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id  INTEGER NOT NULL
                     REFERENCES conversations(id) ON DELETE CASCADE,
    tool             TEXT NOT NULL,
    detail           TEXT NOT NULL,
    decision         TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

-- Full-text search over messages, accent-insensitive so "reunion" finds
-- "réunion". External content: the text lives once, in `messages`, and the
-- triggers keep the index in step.
CREATE VIRTUAL TABLE messages_fts USING fts5(
    body,
    content='messages',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, body) VALUES (new.id, new.body);
END;
CREATE TRIGGER messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, body)
        VALUES ('delete', old.id, old.body);
END;
CREATE TRIGGER messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, body)
        VALUES ('delete', old.id, old.body);
    INSERT INTO messages_fts(rowid, body) VALUES (new.id, new.body);
END;
"""

_V3_CLIP_IMAGES = """
ALTER TABLE clips ADD COLUMN kind TEXT NOT NULL DEFAULT 'text';
ALTER TABLE clips ADD COLUMN image BLOB;
ALTER TABLE clips ADD COLUMN thumbnail BLOB;
"""

#: Index i holds the script that takes the database from version i to i + 1.
MIGRATIONS: tuple[str, ...] = (
    _V1_NOTES_AND_CLIPS,
    _V2_HISTORY,
    _V3_CLIP_IMAGES,
)

LATEST = len(MIGRATIONS)


def version_of(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Bring the database up to LATEST. Returns the versions applied."""
    current = version_of(conn)
    if current > LATEST:
        raise SchemaTooNew(
            f"cette base est en version {current}, cette version de l'app ne "
            f"connaît que la {LATEST} : mettez l'app à jour plutôt que de risquer "
            "vos données"
        )

    applied = []
    for target in range(current + 1, LATEST + 1):
        script = MIGRATIONS[target - 1]
        # executescript commits implicitly, so the transaction is explicit:
        # a step either lands whole, version bump included, or not at all.
        try:
            conn.executescript(
                f"BEGIN;\n{script}\nPRAGMA user_version = {target};\nCOMMIT;"
            )
        except sqlite3.Error:
            # executescript stops at the failing statement with our BEGIN
            # still open; without this, the half-applied step would be
            # committed by whatever the app writes next.
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        applied.append(target)
    return applied
