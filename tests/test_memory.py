"""memory.md: what is sent to Claude, and that the settings window saves it."""

from __future__ import annotations

from wizard.assistant import memory


def test_the_untouched_template_sends_nothing():
    assert memory.for_prompt(memory.TEMPLATE) == ""


def test_html_comments_are_not_sent():
    text = memory.TEMPLATE + "Je tutoie.\n<!-- note pour moi seul -->\n"

    sent = memory.for_prompt(text)
    assert "Je tutoie." in sent
    assert "pour moi seul" not in sent


def test_a_long_memory_is_capped_in_what_is_sent_not_in_the_file(tmp_path):
    path = tmp_path / "memory.md"
    long_text = "x" * (memory.MAX_MEMORY + 500)
    memory.save_memory(long_text, path)

    assert memory.load_memory(path) == long_text
    assert memory.is_truncated(long_text)
    assert len(memory.for_prompt(long_text)) <= memory.MAX_MEMORY + 4


def test_a_missing_file_is_an_empty_memory(tmp_path):
    assert memory.load_memory(tmp_path / "absent.md") == ""


def test_the_session_prompt_includes_the_memory():
    from wizard.claude.session import ClaudeSession

    session = ClaudeSession.__new__(ClaudeSession)
    session._base_prompt = "Base."
    session._memory = "Je code en PHP."

    prompt = session._system_prompt()
    assert prompt.startswith("Base.")
    assert "<memoire>\nJe code en PHP.\n</memoire>" in prompt


def test_no_memory_leaves_the_prompt_alone():
    from wizard.claude.session import ClaudeSession

    session = ClaudeSession.__new__(ClaudeSession)
    session._base_prompt = "Base."
    session._memory = ""

    assert session._system_prompt() == "Base."
