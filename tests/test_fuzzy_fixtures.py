"""The fixtures the TypeScript fuzzy matcher is checked against are fuzzy.py's."""

from __future__ import annotations

import json

from .make_fuzzy_fixtures import PATH, build


def test_fixtures_are_what_fuzzy_py_answers_today():
    on_disk = json.loads(PATH.read_text(encoding="utf-8"))
    assert on_disk == build(), "regenerate with: python tests/make_fuzzy_fixtures.py"
