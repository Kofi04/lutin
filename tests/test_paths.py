"""The rename migration: it must carry the user's data across, exactly once."""

from __future__ import annotations

from wizard.branding import DATABASE_NAME, LEGACY_DATABASE_NAME
from wizard.paths import MARKER_NAME, migrate_legacy_data


def legacy_folder(tmp_path, **files):
    folder = tmp_path / "Lutin"
    folder.mkdir()
    for name, body in files.items():
        (folder / name).write_text(body, encoding="utf-8")
    return folder


def test_copies_config_database_and_state(tmp_path):
    source = legacy_folder(
        tmp_path,
        **{
            "config.toml": "[appearance]\nscale = 2.0\n",
            "state.ini": "[avatar]\nposition=@Point(10 20)\n",
            LEGACY_DATABASE_NAME: "not really sqlite, but bytes are bytes",
        },
    )
    target = tmp_path / "LittleWizard"

    result = migrate_legacy_data(source, target)

    assert result.happened
    assert sorted(result.copied) == sorted(
        ["config.toml", "state.ini", DATABASE_NAME]
    )
    assert (target / "config.toml").read_text(encoding="utf-8") == (
        "[appearance]\nscale = 2.0\n"
    )
    # The database is renamed on the way across.
    assert (target / DATABASE_NAME).exists()
    assert not (target / LEGACY_DATABASE_NAME).exists()


def test_leaves_the_original_untouched(tmp_path):
    source = legacy_folder(tmp_path, **{"config.toml": "x = 1\n"})
    target = tmp_path / "LittleWizard"

    migrate_legacy_data(source, target)

    # Copy, never move: a failed migration must not cost the user their data.
    assert (source / "config.toml").exists()


def test_brings_the_wal_sidecars_along(tmp_path):
    source = legacy_folder(
        tmp_path,
        **{
            LEGACY_DATABASE_NAME: "db",
            f"{LEGACY_DATABASE_NAME}-wal": "wal",
            f"{LEGACY_DATABASE_NAME}-shm": "shm",
        },
    )
    target = tmp_path / "LittleWizard"

    result = migrate_legacy_data(source, target)

    # Leaving the journal behind would make SQLite see a database newer than
    # its own write-ahead log.
    assert f"{DATABASE_NAME}-wal" in result.copied
    assert f"{DATABASE_NAME}-shm" in result.copied


def test_runs_only_once(tmp_path):
    source = legacy_folder(tmp_path, **{"config.toml": "old = true\n"})
    target = tmp_path / "LittleWizard"

    migrate_legacy_data(source, target)
    assert (source / MARKER_NAME).exists()

    # The user edits the new config, then something deletes it. The second run
    # must NOT put the old file back, or every start after a reset would
    # resurrect stale settings and an old database.
    (target / "config.toml").unlink()
    second = migrate_legacy_data(source, target)

    assert not second.happened
    assert second.skipped == "already migrated"
    assert not (target / "config.toml").exists()


def test_never_overwrites_an_existing_file(tmp_path):
    source = legacy_folder(tmp_path, **{"config.toml": "old = true\n"})
    target = tmp_path / "LittleWizard"
    target.mkdir()
    (target / "config.toml").write_text("new = true\n", encoding="utf-8")

    result = migrate_legacy_data(source, target)

    assert result.kept == ["config.toml"]
    assert not result.copied
    assert (target / "config.toml").read_text(encoding="utf-8") == "new = true\n"


def test_no_legacy_folder_is_not_an_error(tmp_path):
    result = migrate_legacy_data(tmp_path / "absent", tmp_path / "LittleWizard")

    assert not result.happened
    assert result.skipped == "no legacy folder"
    assert not result.failures


def test_empty_legacy_folder_is_marked_so_we_stop_looking(tmp_path):
    source = legacy_folder(tmp_path)
    result = migrate_legacy_data(source, tmp_path / "LittleWizard")

    assert result.skipped == "nothing to copy"
    assert (source / MARKER_NAME).exists()


def test_same_folder_is_a_no_op(tmp_path):
    result = migrate_legacy_data(tmp_path, tmp_path)

    assert result.skipped == "same folder"
    assert not (tmp_path / MARKER_NAME).exists()


def test_summary_is_empty_when_nothing_moved(tmp_path):
    result = migrate_legacy_data(tmp_path / "absent", tmp_path / "new")

    assert result.summary() == ""


def test_summary_mentions_the_count_and_reassures(tmp_path):
    source = legacy_folder(
        tmp_path, **{"config.toml": "a = 1\n", LEGACY_DATABASE_NAME: "db"}
    )
    result = migrate_legacy_data(source, tmp_path / "LittleWizard")

    summary = result.summary()
    assert "2 fichiers" in summary
    assert "n'a pas été touché" in summary
