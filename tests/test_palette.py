"""The command palette: gathering, filtering, navigating, running."""

from __future__ import annotations

import pytest

from wizard.ui_palette import KIND_LABELS, Command, CommandPalette


@pytest.fixture
def palette(qt_app):
    widget = CommandPalette()
    yield widget
    widget.deleteLater()


def commands(*titles, kind="action"):
    return [
        Command(title=title, kind=kind, order=index)
        for index, title in enumerate(titles)
    ]


def load(palette, *sources):
    for index, source in enumerate(sources):
        palette.add_source(f"source{index}", source)
    palette._all = palette._gather()
    palette._refilter("")
    return palette


# -- gathering -------------------------------------------------------------


def test_sources_are_combined_and_ordered(palette):
    load(
        palette,
        lambda: [Command(title="second", order=2)],
        lambda: [Command(title="first", order=1)],
    )

    assert [c.title for c in palette._all] == ["first", "second"]


def test_a_failing_source_is_reported_not_swallowed(palette):
    seen = []
    palette.source_failed.connect(lambda name, why: seen.append((name, why)))

    def broken():
        raise RuntimeError("the database is gone")

    load(palette, broken, lambda: commands("survivor"))

    # Hiding this cost real debugging time: a whole category of results simply
    # never appeared, with no symptom at all.
    assert seen and seen[0][0] == "source0"
    assert "database is gone" in seen[0][1]
    # And the other source still works.
    assert [c.title for c in palette._all] == ["survivor"]


def test_sources_are_rebuilt_on_every_open(palette):
    calls = []

    def counting():
        calls.append(1)
        return commands(f"run {len(calls)}")

    palette.add_source("counting", counting)
    palette.open_palette()
    palette.open_palette()

    # Notes and clipboard entries change while the app runs; a cached list
    # would quietly go stale.
    assert len(calls) == 2
    assert palette._all[0].title == "run 2"


# -- filtering -------------------------------------------------------------


def test_an_empty_query_shows_everything(palette):
    load(palette, lambda: commands("alpha", "beta", "gamma"))

    assert len(palette._results) == 3


def test_typing_filters(palette):
    load(palette, lambda: commands("Note rapide", "Presse-papiers"))
    palette._refilter("presse")

    assert [c.title for c in palette._results] == ["Presse-papiers"]


def test_no_match_shows_the_empty_state(palette):
    load(palette, lambda: commands("alpha"))
    palette._refilter("zzzz")

    assert palette._results == []
    assert palette._empty.isVisibleTo(palette)
    assert not palette._list.isVisibleTo(palette)


def test_a_match_hides_the_empty_state(palette):
    load(palette, lambda: commands("alpha"))
    palette._refilter("zzzz")
    palette._refilter("alp")

    assert palette._list.isVisibleTo(palette)
    assert not palette._empty.isVisibleTo(palette)


def test_the_subtitle_and_keywords_are_searchable(palette):
    load(
        palette,
        lambda: [
            Command(title="VS Code", subtitle="code", keywords="editeur developpement")
        ],
    )

    assert palette._refilter("editeur") or len(palette._results) == 1
    palette._refilter("developpement")
    assert len(palette._results) == 1


def test_filtering_selects_the_first_row(palette):
    load(palette, lambda: commands("alpha", "beta"))
    palette._refilter("b")

    assert palette._list.currentRow() == 0
    assert palette.current_command().title == "beta"


# -- navigation ------------------------------------------------------------


def test_moving_down_and_up(palette):
    load(palette, lambda: commands("a", "b", "c"))

    palette._move(1)
    assert palette.current_command().title == "b"
    palette._move(-1)
    assert palette.current_command().title == "a"


def test_navigation_wraps_at_both_ends(palette):
    load(palette, lambda: commands("a", "b", "c"))

    palette._move(-1)
    assert palette.current_command().title == "c"
    palette._move(1)
    assert palette.current_command().title == "a"


def test_moving_in_an_empty_list_is_harmless(palette):
    load(palette, lambda: commands("a"))
    palette._refilter("zzz")

    palette._move(1)
    assert palette.current_command() is None


# -- running ---------------------------------------------------------------


def test_choosing_runs_the_command_and_closes(palette):
    ran = []
    load(palette, lambda: [Command(title="go", run=lambda: ran.append(True))])
    palette.show()

    palette._accept_current()

    assert ran == [True]
    assert not palette.isVisible()


def test_choosing_emits_the_command(palette):
    seen = []
    load(palette, lambda: commands("go"))
    palette.chosen.connect(seen.append)

    palette._accept_current()

    assert seen and seen[0].title == "go"


def test_a_command_without_a_callback_is_not_an_error(palette):
    load(palette, lambda: [Command(title="inert", run=None)])

    palette._accept_current()  # must not raise


def test_accepting_with_no_results_does_nothing(palette):
    load(palette, lambda: commands("a"))
    palette._refilter("zzz")
    seen = []
    palette.chosen.connect(seen.append)

    palette._accept_current()

    assert seen == []


# -- labels ----------------------------------------------------------------


def test_every_kind_used_has_a_french_label():
    for kind in ("action", "launcher", "note", "clip", "conversation"):
        assert kind in KIND_LABELS


def test_the_row_label_shows_the_kind(palette):
    label = palette._label_for(Command(title="Ouvrir", kind="launcher"))

    assert "Ouvrir" in label
    assert KIND_LABELS["launcher"] in label


def test_the_row_label_includes_the_subtitle(palette):
    label = palette._label_for(
        Command(title="VS Code", kind="launcher", subtitle="code.exe")
    )

    assert "code.exe" in label
