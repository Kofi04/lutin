"""Split a Markdown answer into prose and fenced code, and highlight the code.

Qt renders Markdown well enough for prose but draws code blocks as flat grey
text, and it gives no way to put a Copy button on one block. So the answer
panel renders the two differently: prose through Qt's Markdown, each code block
as its own highlighted widget with its own button. This module is the part that
decides where one ends and the next begins.

It must cope with a half-written answer, because answers stream: a fence that
has opened but not closed yet is a code block in progress, not prose with three
backticks in it.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

#: ```lang   or   ~~~lang   — up to three spaces of indent, per CommonMark.
_FENCE = re.compile(r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})(?P<info>[^`]*)$")


@dataclass(frozen=True)
class Block:
    kind: str  # "text" or "code"
    body: str
    language: str = ""
    #: True for a code block whose closing fence has not arrived yet.
    open: bool = False


def split_blocks(markdown: str) -> list[Block]:
    """Break Markdown into alternating prose and code blocks."""
    blocks: list[Block] = []
    prose: list[str] = []
    code: list[str] = []
    fence = ""
    language = ""
    inside = False

    def flush_prose() -> None:
        text = "\n".join(prose).strip("\n")
        if text.strip():
            blocks.append(Block("text", text))
        prose.clear()

    for line in markdown.split("\n"):
        match = _FENCE.match(line)
        if not inside:
            if match:
                flush_prose()
                inside = True
                fence = match.group("fence")
                language = match.group("info").strip().split(" ")[0].lower()
                code.clear()
            else:
                prose.append(line)
            continue

        # Inside a fence: only a matching fence of at least the same length,
        # with nothing after it, closes it. A shorter one is content.
        closing = (
            match is not None
            and match.group("fence")[0] == fence[0]
            and len(match.group("fence")) >= len(fence)
            and not match.group("info").strip()
        )
        if closing:
            blocks.append(Block("code", "\n".join(code), language))
            inside = False
            code.clear()
        else:
            code.append(line)

    if inside:
        # Still streaming: show what has arrived as code, marked open.
        blocks.append(Block("code", "\n".join(code), language, open=True))
    else:
        flush_prose()
    return blocks


#: Pygments styles that sit well on the two themes' field colours.
_STYLES = {True: "one-dark", False: "friendly"}
_FALLBACK_STYLES = {True: "monokai", False: "default"}


def highlight(code: str, language: str, dark: bool) -> str:
    """Code as HTML with inline colours, or escaped plain text as a fallback.

    Inline styles rather than a stylesheet class, because the result goes into a
    Qt rich-text widget, which understands `style=` far more reliably than CSS
    classes.
    """
    try:
        from pygments import highlight as pyg_highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import TextLexer, get_lexer_by_name, guess_lexer
        from pygments.util import ClassNotFound
    except ImportError:  # pragma: no cover - pygments is a declared dependency
        return f"<pre>{html.escape(code)}</pre>"

    try:
        lexer = get_lexer_by_name(language) if language else guess_lexer(code)
    except ClassNotFound:
        lexer = TextLexer()

    formatter = None
    for style in (_STYLES[dark], _FALLBACK_STYLES[dark]):
        try:
            formatter = HtmlFormatter(noclasses=True, nowrap=True, style=style)
            break
        except ClassNotFound:
            continue
    if formatter is None:  # pragma: no cover
        formatter = HtmlFormatter(noclasses=True, nowrap=True)

    body = pyg_highlight(code, lexer, formatter)
    return f'<pre style="margin:0; white-space:pre;">{body}</pre>'


def language_label(language: str) -> str:
    """What to call the language in the block's header."""
    known = {
        "py": "Python",
        "python": "Python",
        "js": "JavaScript",
        "javascript": "JavaScript",
        "ts": "TypeScript",
        "typescript": "TypeScript",
        "sh": "Shell",
        "bash": "Bash",
        "ps1": "PowerShell",
        "powershell": "PowerShell",
        "json": "JSON",
        "toml": "TOML",
        "yaml": "YAML",
        "yml": "YAML",
        "html": "HTML",
        "css": "CSS",
        "sql": "SQL",
        "php": "PHP",
    }
    return known.get(language.lower(), language or "Code")
