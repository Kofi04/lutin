"""SQLite persistence for quick notes and clipboard history.

One small database in the config directory. sqlite3 is in the stdlib and gives
us durability plus full-text-ish search via LIKE, which is plenty at the scale
of a personal clipboard history.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .schema import migrate


@dataclass(frozen=True)
class Record:
    id: int
    body: str
    created_at: datetime
    #: "text" or "image" (clips only; notes are always text).
    kind: str = "text"
    #: A small PNG preview, for image clips.
    thumbnail: bytes | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(UTC)


class Storage:
    """Owns the SQLite connection. Not thread-safe; use it from the GUI thread."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if self.path.name != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        # WAL keeps reads from blocking the UI while a write is in flight.
        if self.path.name != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        # Cascading deletes (a conversation takes its messages with it) are
        # off by default in SQLite, per connection.
        self._conn.execute("PRAGMA foreign_keys = ON")
        #: Versions applied on this open, for the tests and the first-run log.
        self.migrated = migrate(self._conn)

    @property
    def connection(self) -> sqlite3.Connection:
        """Shared with the history store: one database, one connection."""
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Storage:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- notes ------------------------------------------------------------

    def add_note(self, body: str) -> int:
        body = body.strip()
        if not body:
            raise ValueError("impossible d'enregistrer une note vide")
        cursor = self._conn.execute(
            "INSERT INTO notes (body, created_at) VALUES (?, ?)", (body, _now())
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def list_notes(self, limit: int = 50, search: str | None = None) -> list[Record]:
        return self._list("notes", limit, search)

    def delete_note(self, note_id: int) -> None:
        self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self._conn.commit()

    # -- clipboard --------------------------------------------------------

    def add_clip(self, body: str, max_entries: int = 200) -> int | None:
        """Record a clipboard entry, skipping empties and immediate repeats.

        Returns the new row id, or None when the entry was skipped. Repeats are
        common: several apps re-set the clipboard with identical content when a
        window gains focus, and we do not want that to flood the history.
        """
        if not body or not body.strip():
            return None

        latest = self._conn.execute(
            "SELECT body, kind FROM clips ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if latest is not None and latest["kind"] == "text" and latest["body"] == body:
            return None

        cursor = self._conn.execute(
            "INSERT INTO clips (body, created_at) VALUES (?, ?)", (body, _now())
        )
        self._prune_clips(max_entries)
        self._conn.commit()
        return int(cursor.lastrowid)

    def add_image_clip(
        self,
        png: bytes,
        thumbnail: bytes,
        width: int,
        height: int,
        max_entries: int = 200,
        max_images: int = 30,
    ) -> int | None:
        """Record a copied image, skipping an immediate repeat.

        Images are pruned on their own, tighter limit: a screenshot is a
        megabyte where a text clip is a few hundred bytes, and two hundred
        of them would quietly make the database the largest file around.
        """
        if not png:
            return None
        latest = self._conn.execute(
            "SELECT kind, image FROM clips ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if latest is not None and latest["kind"] == "image" and latest["image"] == png:
            return None
        cursor = self._conn.execute(
            "INSERT INTO clips (body, created_at, kind, image, thumbnail)"
            " VALUES (?, ?, 'image', ?, ?)",
            (f"Image {width}×{height}", _now(), png, thumbnail),
        )
        self._conn.execute(
            "DELETE FROM clips WHERE kind = 'image' AND id NOT IN ("
            "  SELECT id FROM clips WHERE kind = 'image' ORDER BY id DESC LIMIT ?"
            ")",
            (max(0, max_images),),
        )
        self._prune_clips(max_entries)
        self._conn.commit()
        return int(cursor.lastrowid)

    def clip_image(self, clip_id: int) -> bytes | None:
        row = self._conn.execute(
            "SELECT image FROM clips WHERE id = ? AND kind = 'image'", (clip_id,)
        ).fetchone()
        return bytes(row["image"]) if row and row["image"] is not None else None

    def list_clips(self, limit: int = 50, search: str | None = None) -> list[Record]:
        return self._list("clips", limit, search)

    def delete_clip(self, clip_id: int) -> None:
        self._conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        self._conn.commit()

    def clear_clips(self) -> None:
        self._conn.execute("DELETE FROM clips")
        self._conn.commit()

    def _prune_clips(self, max_entries: int) -> None:
        """Keep only the newest `max_entries` rows."""
        self._conn.execute(
            "DELETE FROM clips WHERE id NOT IN ("
            "  SELECT id FROM clips ORDER BY id DESC LIMIT ?"
            ")",
            (max_entries,),
        )

    # -- shared -----------------------------------------------------------

    def _list(self, table: str, limit: int, search: str | None) -> list[Record]:
        # `table` is never user input: it is one of two literals from this
        # module, so interpolating it cannot introduce injection.
        assert table in ("notes", "clips")
        extra = ", kind, thumbnail" if table == "clips" else ""
        sql = f"SELECT id, body, created_at{extra} FROM {table}"
        params: list[object] = []
        if search:
            sql += " WHERE body LIKE ? ESCAPE '\\'"
            params.append("%" + _escape_like(search) + "%")
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, limit))

        rows = self._conn.execute(sql, params).fetchall()
        return [
            Record(
                id=row["id"],
                body=row["body"],
                created_at=_parse_time(row["created_at"]),
                kind=row["kind"] if table == "clips" else "text",
                thumbnail=row["thumbnail"] if table == "clips" else None,
            )
            for row in rows
        ]


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so a search for "100%" does not match everything."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
