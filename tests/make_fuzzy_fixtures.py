"""Writes tests/fuzzy_fixtures.json: what fuzzy.py answers, for ui/src/panel/fuzzy.ts.

The bar's "/" filter must rank like the palette (DESIGN.md section 5). The
TypeScript port is checked against these answers; test_fuzzy_fixtures.py
fails if this file and fuzzy.py drift apart. Regenerate with:

    .venv\\Scripts\\python.exe tests\\make_fuzzy_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

from wizard import fuzzy

PATH = Path(__file__).with_name("fuzzy_fixtures.json")

PAIRS = [
    ("", "Notes"),
    ("npr", "Note rapide"),
    ("nr", "Note rapide"),
    ("note", "Notes"),
    ("note", "Notes de réunion"),
    ("reunion", "Notes de réunion"),
    ("REU", "Réunion"),
    ("claude", "Demander à Claude…"),
    ("claude", "C L A U D E autre chose"),
    ("zone", "Montrer une zone…"),
    ("xyz", "Paramètres"),
    ("abc", "ab"),
    ("cap ecr", "capture.screen"),
    ("ecran", "Capturer l'écran"),
    ("q", "quit"),
    ("ç", "Ça marche"),
    ("oe", "Œuvre"),
]

RANKS = [
    ("n", ["Paramètres", "Note rapide", "Notes", "Nouvelle discussion"]),
    ("cl", ["Recharger la configuration", "Demander à Claude…", "Clipboard"]),
    ("", ["b", "a", "c"]),
]


def build() -> dict:
    cases = []
    for query, text in PAIRS:
        hit = fuzzy.score(query, text)
        cases.append(
            {
                "query": query,
                "text": text,
                "score": None if hit is None else round(hit.score, 6),
                "positions": None if hit is None else list(hit.positions),
            }
        )
    ranks = [
        {"query": query, "items": items, "ranked": fuzzy.rank(query, items)}
        for query, items in RANKS
    ]
    return {"about": __doc__.splitlines()[0], "score": cases, "rank": ranks}


if __name__ == "__main__":
    PATH.write_text(
        json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {PATH}")
