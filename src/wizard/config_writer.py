"""Writing config.toml without destroying it.

The settings window has to save, but `config.toml` is a file you own: it is
full of French comments explaining each setting, and you may have edited it by
hand. A TOML serialiser would round-trip the values and throw every comment
away, which would be a quiet act of vandalism on a file the user is told to
read. `tomlkit` would preserve them, at the cost of a dependency.

This does the narrow thing instead: find the one `key = value` line inside the
right `[section]`, replace just the value, keep the trailing comment and the
alignment, and leave every other byte alone. If the key is not there yet it is
appended to its section; if the section is not there, the section is appended.

Scope is deliberately limited to what the settings window writes — scalar
values in flat sections. Arrays of tables (`[[launcher]]`) are left to hand
editing, and this module refuses to touch them rather than guess.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_SECTION = re.compile(r"^\s*\[(?P<name>[A-Za-z0-9_.-]+)\]\s*(#.*)?$")
_ARRAY_SECTION = re.compile(r"^\s*\[\[")
#: key = value   # comment        (the comment is optional)
_ASSIGNMENT = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_-]+)(?P<eq>\s*=\s*)"
    r"(?P<value>.*?)(?P<gap>\s*)(?P<comment>#.*)?$"
)


class ConfigWriteError(ValueError):
    """The requested edit is outside what this writer does safely."""


def format_value(value) -> str:
    """A Python scalar as a TOML literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Always keep a decimal point, so TOML reads it back as a float and
        # the type check in config.py does not reject it.
        text = repr(value)
        return text if any(c in text for c in ".eE") or "inf" in text else f"{text}.0"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        escaped = escaped.replace("\n", "\\n").replace("\t", "\\t")
        return f'"{escaped}"'
    raise ConfigWriteError(f"type non pris en charge : {type(value).__name__}")


@dataclass(frozen=True)
class Edit:
    section: str
    key: str
    value: object


def apply_edits(text: str, edits: list[Edit]) -> str:
    """Return `text` with each edit applied, and nothing else changed."""
    lines = text.splitlines(keepends=True)
    for edit in edits:
        lines = _apply_one(lines, edit)
    result = "".join(lines)
    # The whole point is not to corrupt the file; prove it parses before
    # anyone writes it to disk.
    try:
        tomllib.loads(result)
    except tomllib.TOMLDecodeError as exc:  # pragma: no cover - a bug if hit
        raise ConfigWriteError(f"l'édition produirait un TOML invalide : {exc}") from exc
    return result


def _apply_one(lines: list[str], edit: Edit) -> list[str]:
    rendered = format_value(edit.value)
    start, end = _section_bounds(lines, edit.section)

    if start is None:
        # No such section: append it, with a blank line before for breathing.
        tail = lines[:]
        if tail and not tail[-1].endswith("\n"):
            tail[-1] += "\n"
        if tail and tail[-1].strip():
            tail.append("\n")
        tail.append(f"[{edit.section}]\n")
        tail.append(f"{edit.key} = {rendered}\n")
        return tail

    for index in range(start + 1, end):
        match = _ASSIGNMENT.match(lines[index].rstrip("\r\n"))
        if match is None or match.group("key") != edit.key:
            continue
        newline = _newline_of(lines[index])
        comment = match.group("comment") or ""
        gap = match.group("gap") if comment else ""
        # Keep the comment column where the user put it, where possible.
        if comment:
            before = f"{match.group('indent')}{edit.key}{match.group('eq')}{rendered}"
            old_width = len(
                f"{match.group('indent')}{edit.key}{match.group('eq')}"
                f"{match.group('value')}"
            )
            gap = " " * max(1, old_width + len(match.group("gap")) - len(before))
            lines[index] = f"{before}{gap}{comment}{newline}"
        else:
            lines[index] = (
                f"{match.group('indent')}{edit.key}{match.group('eq')}"
                f"{rendered}{newline}"
            )
        return lines

    # Section exists, key does not: add it at the end of the section, before
    # any trailing blank lines so the file keeps its shape.
    insert_at = end
    while insert_at > start + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1
    newline = _newline_of(lines[start])
    lines.insert(insert_at, f"{edit.key} = {rendered}{newline}")
    return lines


def _section_bounds(lines: list[str], section: str) -> tuple[int | None, int]:
    """(header line, first line after the section) or (None, len(lines))."""
    start = None
    for index, line in enumerate(lines):
        if _ARRAY_SECTION.match(line):
            if start is not None:
                return start, index
            continue
        header = _SECTION.match(line.rstrip("\r\n"))
        if header is None:
            continue
        if start is not None:
            return start, index
        if header.group("name") == section:
            start = index
    return (start, len(lines)) if start is not None else (None, len(lines))


def _newline_of(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return "\n"


def write_edits(path: Path, edits: list[Edit]) -> None:
    """Apply edits to the file on disk, atomically."""
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = apply_edits(original, edits)
    if updated == original:
        return
    # Write beside it and swap, so a crash mid-write cannot leave a half file
    # that the next start would reject.
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(updated, encoding="utf-8", newline="")
    temporary.replace(path)
