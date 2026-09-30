"""The command palette's ranking. A palette lives or dies on this."""

from __future__ import annotations

import pytest

from wizard.fuzzy import fold, rank, score


def best(query: str, *candidates: str) -> str:
    return rank(query, list(candidates))[0]


# -- matching --------------------------------------------------------------


def test_an_exact_match_matches():
    assert score("note", "Note rapide") is not None


def test_a_subsequence_matches():
    assert score("nr", "Note rapide") is not None
    assert score("nrpd", "Note rapide") is not None


def test_a_subsequence_must_be_in_order():
    # "p" comes after "r" in "Note rapide", so "npr" genuinely does not match.
    assert score("npr", "Note rapide") is None


def test_a_missing_character_does_not_match():
    assert score("xyz", "Note rapide") is None


def test_order_matters():
    # "ar" is in "rapide" but not in that order from the start of "Note".
    assert score("etno", "Note") is None


def test_an_empty_query_matches_everything():
    assert score("", "anything") is not None


def test_nothing_matches_an_empty_haystack():
    assert score("a", "") is None


def test_a_query_longer_than_the_text_cannot_match():
    assert score("abcdefghij", "abc") is None


# -- accents ---------------------------------------------------------------


def test_accents_are_folded():
    # On a French interface, needing the accent to search is the difference
    # between a palette you use and one you abandon.
    assert fold("Réunion") == "reunion"
    assert score("reunion", "Réunion d'équipe") is not None
    assert score("Réunion", "reunion d'equipe") is not None


def test_case_is_ignored():
    assert score("NOTE", "note rapide") is not None


@pytest.mark.parametrize(
    ("query", "text"),
    [("ecran", "Montrer une zone d'écran"), ("cafe", "Café"), ("ou", "Où ?")],
)
def test_folded_queries_find_accented_text(query, text):
    assert score(query, text) is not None


# -- ranking ---------------------------------------------------------------


def test_a_prefix_beats_a_match_in_the_middle():
    assert best("note", "Note rapide", "Ouvrir une note") == "Note rapide"


def test_a_word_boundary_beats_the_middle_of_a_word():
    assert best("rap", "Note rapide", "Therapie") == "Note rapide"


def test_consecutive_characters_beat_scattered_ones():
    assert best("cap", "Capture", "Corriger a partir de p") == "Capture"


def test_the_shorter_of_two_matches_wins():
    assert best("note", "Notes", "Notes de la réunion de mardi") == "Notes"


def test_an_exact_word_beats_an_initialism():
    assert best("claude", "Demander à Claude", "C L A U D E autre chose") == (
        "Demander à Claude"
    )


def test_ranking_drops_what_does_not_match():
    results = rank("zzz", ["Note rapide", "Presse-papiers"])

    assert results == []


def test_an_empty_query_preserves_the_given_order():
    # That order is usually meaningful: most recent first, or hand-arranged.
    items = ["c", "a", "b"]

    assert rank("", items) == items
    assert rank("   ", items) == items


def test_ranking_is_stable_for_equal_scores():
    items = ["aX", "aY", "aZ"]

    assert rank("a", items) == items


def test_the_limit_is_respected():
    items = [f"note {i}" for i in range(50)]

    assert len(rank("note", items, limit=5)) == 5
    assert len(rank("", items, limit=3)) == 3


def test_ranking_uses_the_key_it_is_given():
    items = [{"label": "Note rapide"}, {"label": "Presse-papiers"}]

    results = rank("note", items, key=lambda item: item["label"])

    assert results == [{"label": "Note rapide"}]


# -- positions, for highlighting ------------------------------------------


def test_positions_point_at_the_matched_characters():
    hit = score("nr", "note rapide")

    assert hit is not None
    folded = fold("note rapide")
    assert "".join(folded[i] for i in hit.positions) == "nr"


def test_positions_are_in_order_and_unique():
    hit = score("nrp", "note rapide")

    assert list(hit.positions) == sorted(set(hit.positions))


def test_spaces_in_a_query_are_ignored_as_literals():
    # "n r" means "n then r", not a literal space between them.
    assert score("n r", "note rapide") is not None
    assert score("no ra", "note rapide") is not None
