"""The answer panel: streaming, then a finished render with copyable code."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QGuiApplication

from wizard.ui_claude import AskPanel, CodeBlock

ANSWER = (
    "Explication.\n\n"
    "```python\nfor item in items[:]:\n    items.remove(item)\n```\n\n"
    "Fin."
)


@pytest.fixture
def panel():
    widget = AskPanel()
    widget.resize(620, 560)
    yield widget
    widget.deleteLater()


def code_blocks(panel):
    page = panel._blocks.widget()
    return page.findChildren(CodeBlock) if page is not None else []


def test_streaming_uses_the_plain_view(panel):
    panel.append_answer("Premier morceau")

    assert panel._view.isVisibleTo(panel)
    assert not panel._blocks.isVisibleTo(panel)


def test_a_finished_answer_with_code_gets_the_block_view(panel):
    panel.append_answer(ANSWER)
    panel.finish("1 tour")

    assert panel._blocks.isVisibleTo(panel)
    assert not panel._view.isVisibleTo(panel)
    assert len(code_blocks(panel)) == 1


def test_a_finished_answer_without_code_stays_simple(panel):
    # No code, nothing to highlight: rebuilding widgets would be pure cost.
    panel.append_answer("Juste du texte, sans code.")
    panel.finish()

    assert panel._view.isVisibleTo(panel)
    assert code_blocks(panel) == []


def test_each_code_block_copies_exactly_its_own_code(panel):
    panel.append_answer(ANSWER)
    panel.finish()
    block = code_blocks(panel)[0]

    block._copy()

    assert QGuiApplication.clipboard().text() == (
        "for item in items[:]:\n    items.remove(item)"
    )


def test_copying_gives_visible_feedback(panel):
    panel.append_answer(ANSWER)
    panel.finish()
    block = code_blocks(panel)[0]

    block._copy()

    assert block._button.text() == "Copié"


def test_a_new_stream_after_a_finished_one_goes_back_to_plain(panel):
    panel.append_answer(ANSWER)
    panel.finish()
    panel.reset_answer()
    panel.append_answer("Nouvelle réponse")

    assert panel._view.isVisibleTo(panel)
    assert not panel._blocks.isVisibleTo(panel)


def test_an_error_after_a_rendered_answer_is_visible(panel):
    panel.append_answer(ANSWER)
    panel.finish()
    panel.show_error("Claude Code n'est pas connecté.")

    # The failure must not be hidden behind the previous answer's blocks.
    assert panel._view.isVisibleTo(panel)
    assert "pas connecté" in panel._view.toPlainText()
