"""The user's memory.md: what Claude should know about them, in their words.

A plain Markdown file in the config folder — "je tutoie", "je code en Python
et PHP", "mon équipe s'appelle…" — edited from the settings window or in any
editor, and appended to Claude's system prompt.

It is sent with every conversation, so it is capped: past a few thousand
characters it costs tokens on every question and dilutes the instructions it
sits beside. Anything longer is truncated *in what is sent*, never in the file,
and the settings window says so.
"""

from __future__ import annotations

from pathlib import Path

from ..paths import config_dir

#: Sent with every question; past this, it costs more than it helps.
MAX_MEMORY = 6000

TEMPLATE = (
    "# Ma mémoire\n"
    "\n"
    "<!-- Ce que Little Wizard doit savoir sur vous. Envoyé à Claude avec chaque\n"
    "question : n'y mettez rien de secret. -->\n"
    "\n"
)


def memory_path() -> Path:
    return config_dir() / "memory.md"


def load_memory(path: Path | None = None) -> str:
    """The file's content, or empty if it does not exist or cannot be read."""
    target = path or memory_path()
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def save_memory(text: str, path: Path | None = None) -> None:
    target = path or memory_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".md.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(target)


def for_prompt(text: str) -> str:
    """What is actually sent: comments stripped, blank if nothing real, capped."""
    import re

    cleaned = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # A file that is only the template's heading says nothing about the user.
    meaningful = [
        line
        for line in cleaned.splitlines()
        if line.strip() and not line.startswith("# ")
    ]
    if not meaningful:
        return ""
    cleaned = cleaned.strip()
    if len(cleaned) > MAX_MEMORY:
        cleaned = cleaned[:MAX_MEMORY].rstrip() + "\n[…]"
    return cleaned


def is_truncated(text: str) -> bool:
    return len(for_prompt(text)) > MAX_MEMORY
