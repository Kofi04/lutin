"""Read-only access to the Claude Code sessions you run yourself.

Claude Code writes one JSONL file per session under
`~/.claude/projects/<encoded project path>/<session id>.jsonl`. Each line is an
event; the ones that matter here are `user` and `assistant` (with
`message.content` either a string or a list of blocks), `ai-title` and
`last-prompt`. Everything else — attachments, cost state, queue operations — is
skipped.

**Read-only, always.** This module opens those files for reading and never
writes, moves or deletes one: they are Claude Code's state, and corrupting a
transcript can break resuming that session in the terminal.

The format is Claude Code's, not ours, and it changes between versions. So the
parser is tolerant by construction: an unknown line type is ignored, a
malformed line is skipped, and a file that yields nothing readable is simply
not listed. It never raises on a transcript.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: Past this, a session list stops being a list anyone reads.
MAX_SESSIONS = 200
#: Titles come from the first lines; no need to parse a whole 50 MB file.
_HEAD_LINES = 400


def projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


@dataclass(frozen=True)
class TranscriptSession:
    path: Path
    session_id: str
    project: str
    title: str
    modified: datetime
    size: int


@dataclass(frozen=True)
class TranscriptMessage:
    role: str  # "user" | "assistant"
    text: str
    timestamp: datetime | None
    #: Short notes about non-text content ("image", "outil : Bash").
    extras: tuple[str, ...] = ()


def _text_of(content) -> tuple[str, tuple[str, ...]]:
    """The human-readable text of a message, plus notes on what else it held."""
    if isinstance(content, str):
        return content, ()
    if not isinstance(content, list):
        return "", ()
    texts: list[str] = []
    extras: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text" and isinstance(block.get("text"), str):
            texts.append(block["text"])
        elif kind == "image":
            extras.append("image")
        elif kind == "tool_use":
            extras.append(f"outil : {block.get('name', '?')}")
        # thinking and tool_result blocks are deliberately not shown: one is
        # internal reasoning, the other is often a wall of tool output.
    return "\n\n".join(texts), tuple(extras)


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _project_name(directory: Path, cwd: str | None) -> str:
    if cwd:
        return Path(cwd).name or cwd
    # The directory name encodes the path with dashes; its tail is usually the
    # project folder, which is good enough for a label.
    return directory.name.rsplit("-", 1)[-1] or directory.name


def read_messages(path: Path) -> list[TranscriptMessage]:
    """The conversation in a transcript, in order. Never raises."""
    messages: list[TranscriptMessage] = []
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return messages
    with handle:
        for line in handle:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or event.get("isSidechain"):
                # Sidechains are subagent conversations, not yours.
                continue
            kind = event.get("type")
            if kind not in ("user", "assistant"):
                continue
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            text, extras = _text_of(message.get("content"))
            if not text.strip() and not extras:
                continue
            # A "user" turn made only of tool results is the harness talking,
            # not the person.
            if kind == "user" and not text.strip() and "image" not in extras:
                continue
            messages.append(
                TranscriptMessage(
                    kind, text.strip(), _parse_time(event.get("timestamp")), extras
                )
            )
    return messages


def _describe(path: Path) -> TranscriptSession | None:
    title = ""
    first_prompt = ""
    cwd: str | None = None
    try:
        stat = path.stat()
        with path.open(encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= _HEAD_LINES and (title or first_prompt):
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                cwd = cwd or event.get("cwd")
                kind = event.get("type")
                if kind == "ai-title" and isinstance(event.get("aiTitle"), str):
                    title = event["aiTitle"]
                elif kind == "user" and not first_prompt and not event.get("isSidechain"):
                    message = event.get("message")
                    if not isinstance(message, dict):
                        continue
                    text, _ = _text_of(message.get("content"))
                    first_prompt = text.strip()
    except OSError:
        return None

    label = title or first_prompt
    if not label:
        return None
    label = " ".join(label.split())
    if len(label) > 80:
        label = label[:79] + "…"
    return TranscriptSession(
        path=path,
        session_id=path.stem,
        project=_project_name(path.parent, cwd),
        title=label,
        modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        size=stat.st_size,
    )


def list_sessions(
    root: Path | None = None, limit: int = MAX_SESSIONS
) -> list[TranscriptSession]:
    """Your Claude Code sessions, most recently active first."""
    base = root if root is not None else projects_dir()
    if not base.is_dir():
        return []
    files = sorted(
        (f for f in base.glob("*/*.jsonl") if f.is_file()),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    sessions: list[TranscriptSession] = []
    for path in files:
        described = _describe(path)
        if described is not None:
            sessions.append(described)
        if len(sessions) >= limit:
            break
    return sessions


def as_markdown(session: TranscriptSession) -> str:
    """A transcript rendered for reading."""
    lines = [f"# {session.title}", "", f"*{session.project} · {session.session_id}*", ""]
    for message in read_messages(session.path):
        who = "Vous" if message.role == "user" else "Claude"
        lines.append(f"**{who}**")
        lines.append("")
        if message.extras:
            lines.append("> " + " · ".join(message.extras))
            lines.append("")
        if message.text:
            lines.append(message.text)
            lines.append("")
    return "\n".join(lines)
