"""Splitting an answer into prose and code — including a half-streamed one."""

from __future__ import annotations

import pytest

from wizard.markdown_blocks import highlight, language_label, split_blocks


def kinds(blocks):
    return [block.kind for block in blocks]


def test_plain_prose_is_one_block():
    blocks = split_blocks("Bonjour.\n\nUne deuxième phrase.")

    assert kinds(blocks) == ["text"]


def test_a_code_block_between_prose():
    blocks = split_blocks("Avant.\n\n```python\nprint('hi')\n```\n\nAprès.")

    assert kinds(blocks) == ["text", "code", "text"]
    assert blocks[1].body == "print('hi')"
    assert blocks[1].language == "python"
    assert not blocks[1].open


def test_the_language_is_the_first_word_of_the_info_string():
    blocks = split_blocks("```js title=app.js\nlet x = 1\n```")

    assert blocks[0].language == "js"


def test_a_fence_without_a_language():
    blocks = split_blocks("```\nplain\n```")

    assert blocks[0].language == ""
    assert blocks[0].body == "plain"


def test_tilde_fences_work_too():
    blocks = split_blocks("~~~\ncode\n~~~")

    assert kinds(blocks) == ["code"]


def test_an_unclosed_fence_is_an_open_code_block():
    # Answers stream: this is the state for most of a code block's life, and
    # treating it as prose would flash raw backticks at the user.
    blocks = split_blocks("Voici :\n\n```python\ndef f():\n    return 1")

    assert kinds(blocks) == ["text", "code"]
    assert blocks[1].open
    assert "return 1" in blocks[1].body


def test_a_shorter_fence_inside_is_content_not_a_close():
    text = "````markdown\n```python\nx\n```\n````"
    blocks = split_blocks(text)

    assert kinds(blocks) == ["code"]
    assert "```python" in blocks[0].body


def test_a_fence_with_trailing_text_does_not_close():
    blocks = split_blocks("```\na\n``` not a close\nb\n```")

    assert kinds(blocks) == ["code"]
    assert "not a close" in blocks[0].body


def test_indentation_inside_code_is_preserved():
    blocks = split_blocks("```py\ndef f():\n    if x:\n        return 1\n```")

    assert "        return 1" in blocks[0].body


def test_empty_prose_between_blocks_is_dropped():
    blocks = split_blocks("```\na\n```\n\n\n```\nb\n```")

    assert kinds(blocks) == ["code", "code"]


def test_an_empty_answer_has_no_blocks():
    assert split_blocks("") == []


def test_the_streaming_sequence_never_loses_text():
    full = "Intro.\n\n```python\nprint(1)\nprint(2)\n```\n\nFin."
    # Every prefix of a streamed answer must split without losing or
    # duplicating the code that has arrived so far.
    for cut in range(len(full) + 1):
        blocks = split_blocks(full[:cut])
        joined = "\n".join(block.body for block in blocks)
        for fragment in ("print(1)", "print(2)"):
            if fragment in full[:cut]:
                assert fragment in joined, f"lost {fragment!r} at cut {cut}"


# -- highlighting ----------------------------------------------------------


@pytest.mark.parametrize("dark", [True, False])
def test_known_languages_are_coloured(dark):
    html = highlight("def f():\n    return 1", "python", dark)

    assert "style=" in html
    assert "def" in html


def test_code_is_escaped():
    # Code in an answer is data, never markup to render.
    html = highlight("<script>alert(1)</script>", "text", True)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_an_unknown_language_falls_back_to_plain():
    html = highlight("some text", "not-a-real-language", True)

    assert "some text" in html


def test_no_language_does_not_crash():
    assert "x = 1" in highlight("x = 1", "", False)


@pytest.mark.parametrize(
    ("given", "expected"),
    [("py", "Python"), ("ps1", "PowerShell"), ("", "Code"), ("rust", "rust")],
)
def test_language_labels(given, expected):
    assert language_label(given) == expected
