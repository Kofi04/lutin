"""Notes and clipboard persistence."""

from __future__ import annotations

import pytest

from lutin.storage import Storage


@pytest.fixture
def storage(tmp_path):
    with Storage(tmp_path / "test.db") as store:
        yield store


def test_notes_round_trip_newest_first(storage):
    storage.add_note("first")
    storage.add_note("second")

    bodies = [record.body for record in storage.list_notes()]

    assert bodies == ["second", "first"]


def test_notes_are_trimmed_and_cannot_be_empty(storage):
    storage.add_note("  padded  ")
    assert storage.list_notes()[0].body == "padded"

    with pytest.raises(ValueError):
        storage.add_note("   ")


def test_deleting_a_note(storage):
    note_id = storage.add_note("temporary")
    storage.delete_note(note_id)

    assert storage.list_notes() == []


def test_clipboard_skips_consecutive_duplicates(storage):
    assert storage.add_clip("hello") is not None
    assert storage.add_clip("hello") is None  # same as the latest entry
    assert storage.add_clip("world") is not None
    assert storage.add_clip("hello") is not None  # no longer the latest

    assert [record.body for record in storage.list_clips()] == [
        "hello",
        "world",
        "hello",
    ]


def test_clipboard_skips_blank_entries(storage):
    assert storage.add_clip("") is None
    assert storage.add_clip("   \n\t ") is None
    assert storage.list_clips() == []


def test_clipboard_prunes_to_max_entries(storage):
    for index in range(10):
        storage.add_clip(f"entry-{index}", max_entries=3)

    bodies = [record.body for record in storage.list_clips()]

    assert bodies == ["entry-9", "entry-8", "entry-7"]


def test_clear_clips_leaves_notes_alone(storage):
    storage.add_note("keep me")
    storage.add_clip("drop me")

    storage.clear_clips()

    assert storage.list_clips() == []
    assert len(storage.list_notes()) == 1


def test_search_filters_results(storage):
    storage.add_note("buy milk")
    storage.add_note("call the bank")

    assert [r.body for r in storage.list_notes(search="milk")] == ["buy milk"]
    assert storage.list_notes(search="zzz") == []


def test_search_treats_wildcards_literally(storage):
    storage.add_note("battery at 100%")
    storage.add_note("nothing special")

    # Without LIKE escaping, "100%" would match every row.
    assert [r.body for r in storage.list_notes(search="100%")] == ["battery at 100%"]
    assert storage.list_notes(search="_") == []


def test_database_survives_reopening(tmp_path):
    path = tmp_path / "persist.db"
    with Storage(path) as store:
        store.add_note("durable")

    with Storage(path) as store:
        assert [record.body for record in store.list_notes()] == ["durable"]
