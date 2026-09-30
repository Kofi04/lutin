"""Every conversation with Claude, kept locally and searchable.

Shares the app's SQLite connection (see `storage.py`): one database file, one
place to back up, one place to wipe.

Things worth knowing:

* **Search is FTS5, accent-insensitive.** "reunion" finds "réunion". The user's
  words are turned into quoted prefix terms before reaching FTS5, so typing a
  quote, a dash or `OR` searches for it instead of being parsed as query syntax
  — or raising, which is what raw FTS5 does with an unbalanced quote.
* **Only thumbnails are stored for captures**, never the full image. A history
  of screenshots is a history of everything that was on screen; a 256 px
  thumbnail is enough to recognise the conversation and far less of a liability.
* **Pinned conversations survive retention purges and are listed first.**
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

#: What started the conversation, for the filters.
KINDS = {
    "question": "Question",
    "voice": "Voix",
    "live": "Live",
    "agent": "Agent",
    "selection": "Sélection",
}

_TITLE_LENGTH = 60


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _parse(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return _now()
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def title_from(text: str) -> str:
    """A conversation title from its first question."""
    single = " ".join(text.split())
    if len(single) <= _TITLE_LENGTH:
        return single
    return single[: _TITLE_LENGTH - 1].rstrip() + "…"


def fts_query(text: str) -> str | None:
    """Turn what the user typed into a safe FTS5 query, or None if empty.

    Each word becomes a quoted prefix term ("reun"* matches "réunion"), joined
    by an implicit AND. Nothing the user types can reach FTS5 as syntax.
    """
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    if not words:
        return None
    return " ".join(f'"{word}"*' for word in words)


@dataclass(frozen=True)
class Conversation:
    id: int
    kind: str
    title: str
    started_at: datetime
    updated_at: datetime
    sdk_session_id: str | None
    project: str
    pinned: bool


@dataclass(frozen=True)
class CaptureInfo:
    kind: str
    label: str
    width: int
    height: int
    thumbnail: bytes | None = None


@dataclass(frozen=True)
class Message:
    id: int
    role: str  # "user" | "assistant" | "error"
    body: str
    created_at: datetime
    captures: tuple[CaptureInfo, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ToolCall:
    tool: str
    detail: str
    decision: str
    created_at: datetime


@dataclass(frozen=True)
class SearchHit:
    conversation: Conversation
    #: The matching passage, with the hit wrapped in [ ].
    snippet: str


class HistoryStore:
    """Conversations, messages, capture thumbnails and tool decisions."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # -- writing ------------------------------------------------------------

    def start(self, kind: str = "question", title: str = "", project: str = "") -> int:
        now = _iso(_now())
        cursor = self._conn.execute(
            "INSERT INTO conversations (kind, title, started_at, updated_at, project)"
            " VALUES (?, ?, ?, ?, ?)",
            (kind, title_from(title) if title else "", now, now, project),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def add_message(
        self,
        conversation_id: int,
        role: str,
        body: str,
        capture: CaptureInfo | None = None,
    ) -> int:
        now = _iso(_now())
        cursor = self._conn.execute(
            "INSERT INTO messages (conversation_id, role, body, created_at)"
            " VALUES (?, ?, ?, ?)",
            (conversation_id, role, body, now),
        )
        message_id = int(cursor.lastrowid)
        if capture is not None:
            self._conn.execute(
                "INSERT INTO captures (message_id, kind, label, width, height, thumbnail)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    capture.kind,
                    capture.label,
                    capture.width,
                    capture.height,
                    capture.thumbnail,
                ),
            )
        # The first question names the conversation, unless someone already did.
        self._conn.execute(
            "UPDATE conversations SET updated_at = ?,"
            " title = CASE WHEN title = '' AND ? = 'user' THEN ? ELSE title END"
            " WHERE id = ?",
            (now, role, title_from(body), conversation_id),
        )
        self._conn.commit()
        return message_id

    def set_session(self, conversation_id: int, sdk_session_id: str) -> None:
        """Remember the Claude Code session, so the conversation can be resumed."""
        self._conn.execute(
            "UPDATE conversations SET sdk_session_id = ? WHERE id = ?",
            (sdk_session_id, conversation_id),
        )
        self._conn.commit()

    def record_tool(
        self, conversation_id: int, tool: str, detail: str, decision: str
    ) -> None:
        self._conn.execute(
            "INSERT INTO tool_calls (conversation_id, tool, detail, decision, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (conversation_id, tool, detail[:2000], decision, _iso(_now())),
        )
        self._conn.commit()

    def rename(self, conversation_id: int, title: str) -> None:
        self._conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            (title.strip()[:200], conversation_id),
        )
        self._conn.commit()

    def pin(self, conversation_id: int, pinned: bool = True) -> None:
        self._conn.execute(
            "UPDATE conversations SET pinned = ? WHERE id = ?",
            (int(pinned), conversation_id),
        )
        self._conn.commit()

    def delete(self, conversation_id: int) -> None:
        self._conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        self._conn.commit()

    def clear(self) -> int:
        """Delete every conversation, pinned ones included. Returns how many."""
        count = self._conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        self._conn.execute("DELETE FROM conversations")
        # Rebuilding the index also reclaims the space the deleted text used.
        self._conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
        self._conn.commit()
        return int(count)

    def purge_older_than(self, days: int, now: datetime | None = None) -> int:
        """Retention: drop unpinned conversations untouched for `days`. 0 = keep all."""
        if days <= 0:
            return 0
        cutoff = _iso((now or _now()) - timedelta(days=days))
        cursor = self._conn.execute(
            "DELETE FROM conversations WHERE pinned = 0 AND updated_at < ?", (cutoff,)
        )
        self._conn.commit()
        return int(cursor.rowcount)

    # -- reading ------------------------------------------------------------

    def conversation(self, conversation_id: int) -> Conversation | None:
        row = self._conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return _conversation(row) if row else None

    def conversations(
        self, kind: str | None = None, limit: int = 300
    ) -> list[Conversation]:
        """Newest first, pinned ones on top."""
        sql = "SELECT * FROM conversations"
        params: list[object] = []
        if kind:
            sql += " WHERE kind = ?"
            params.append(kind)
        sql += " ORDER BY pinned DESC, updated_at DESC, id DESC LIMIT ?"
        params.append(max(1, limit))
        return [_conversation(row) for row in self._conn.execute(sql, params)]

    def messages(self, conversation_id: int) -> list[Message]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
        result = []
        for row in rows:
            captures = tuple(
                CaptureInfo(
                    c["kind"], c["label"], c["width"], c["height"], c["thumbnail"]
                )
                for c in self._conn.execute(
                    "SELECT * FROM captures WHERE message_id = ? ORDER BY id",
                    (row["id"],),
                )
            )
            result.append(
                Message(
                    id=row["id"],
                    role=row["role"],
                    body=row["body"],
                    created_at=_parse(row["created_at"]),
                    captures=captures,
                )
            )
        return result

    def tool_calls(self, conversation_id: int) -> list[ToolCall]:
        return [
            ToolCall(
                row["tool"], row["detail"], row["decision"], _parse(row["created_at"])
            )
            for row in self._conn.execute(
                "SELECT * FROM tool_calls WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            )
        ]

    def search(
        self, text: str, kind: str | None = None, limit: int = 100
    ) -> list[SearchHit]:
        """Conversations whose messages match, best match first, one hit each."""
        query = fts_query(text)
        if query is None:
            return []
        sql = (
            "SELECT c.*, snippet(messages_fts, 0, '[', ']', '…', 12) AS snip,"
            " bm25(messages_fts) AS rank"
            " FROM messages_fts"
            " JOIN messages m ON m.id = messages_fts.rowid"
            " JOIN conversations c ON c.id = m.conversation_id"
            " WHERE messages_fts MATCH ?"
        )
        params: list[object] = [query]
        if kind:
            sql += " AND c.kind = ?"
            params.append(kind)
        sql += " ORDER BY rank LIMIT ?"
        params.append(max(1, limit) * 5)

        seen: set[int] = set()
        hits: list[SearchHit] = []
        for row in self._conn.execute(sql, params):
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            hits.append(SearchHit(_conversation(row), row["snip"]))
            if len(hits) >= limit:
                break
        # A title match counts too, even if no message contains the words.
        for conversation in self._title_matches(text, kind):
            if conversation.id not in seen:
                seen.add(conversation.id)
                hits.append(SearchHit(conversation, conversation.title))
        return hits

    def _title_matches(self, text: str, kind: str | None) -> list[Conversation]:
        from .fuzzy import fold

        needle = fold(text.strip())
        if not needle:
            return []
        return [c for c in self.conversations(kind) if needle in fold(c.title)]

    # -- export -------------------------------------------------------------

    def export_markdown(self, conversation_id: int) -> str:
        conversation = self.conversation(conversation_id)
        if conversation is None:
            return ""
        local = conversation.started_at.astimezone()
        lines = [
            f"# {conversation.title or 'Discussion'}",
            "",
            f"*{KINDS.get(conversation.kind, conversation.kind)} · "
            f"{local:%d/%m/%Y %H:%M}*",
            "",
        ]
        for message in self.messages(conversation_id):
            who = {"user": "Vous", "assistant": "Claude", "error": "Erreur"}.get(
                message.role, message.role
            )
            lines.append(f"## {who}")
            lines.append("")
            for capture in message.captures:
                lines.append(
                    f"> Capture : {capture.label} ({capture.width}×{capture.height})"
                )
                lines.append("")
            lines.append(message.body.rstrip())
            lines.append("")
        calls = self.tool_calls(conversation_id)
        if calls:
            lines.append("## Actions demandées")
            lines.append("")
            for call in calls:
                lines.append(f"- `{call.tool}` — {call.decision} — {call.detail[:120]}")
            lines.append("")
        return "\n".join(lines)


def _conversation(row) -> Conversation:
    return Conversation(
        id=row["id"],
        kind=row["kind"],
        title=row["title"],
        started_at=_parse(row["started_at"]),
        updated_at=_parse(row["updated_at"]),
        sdk_session_id=row["sdk_session_id"],
        project=row["project"],
        pinned=bool(row["pinned"]),
    )


def group_by_date(
    conversations: list[Conversation], now: datetime | None = None
) -> list[tuple[str, list[Conversation]]]:
    """Aujourd'hui / Hier / Cette semaine / Ce mois-ci / Plus ancien, pinned first.

    Days are counted in local time: "hier" means the user's yesterday, not
    UTC's, which differ for part of every evening.
    """
    today = (now or _now()).astimezone().date()
    buckets: dict[str, list[Conversation]] = {}
    order = [
        "Épinglées",
        "Aujourd'hui",
        "Hier",
        "Cette semaine",
        "Ce mois-ci",
        "Plus ancien",
    ]
    for conversation in conversations:
        if conversation.pinned:
            label = "Épinglées"
        else:
            day = conversation.updated_at.astimezone().date()
            age = (today - day).days
            if age <= 0:
                label = "Aujourd'hui"
            elif age == 1:
                label = "Hier"
            elif age < 7:
                label = "Cette semaine"
            elif age < 31:
                label = "Ce mois-ci"
            else:
                label = "Plus ancien"
        buckets.setdefault(label, []).append(conversation)
    return [(label, buckets[label]) for label in order if label in buckets]
