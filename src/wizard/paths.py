"""Where the app keeps its files, and how it moved there.

The app used to be called "Lutin", so its data lived in %APPDATA%\\Lutin. The
rename to "Little Wizard" changes SLUG, which changes the folder, which would
silently orphan the user's notes, clipboard history, settings and saved avatar
position. This module carries them across.

Two decisions worth knowing about:

* **It copies, it never moves.** The old folder is left exactly as it was, so a
  failed migration costs nothing and the user still has their data. Disk space
  for a few KB of notes is not worth the risk of being the code that deleted
  someone's history.
* **A marker file, not "does the target exist", decides whether we are done.**
  Without the marker, deleting the new config.toml would make the next start
  copy the old database over the new one, losing everything written since. The
  marker makes the migration happen exactly once.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .branding import (
    DATABASE_NAME,
    LEGACY_DATABASE_NAME,
    LEGACY_SLUG,
    SLUG,
)

#: Written into the old folder once its contents have been copied across.
MARKER_NAME = f".migrated-to-{SLUG}"

#: Old name -> new name. The database is renamed on the way; the -wal and -shm
#: sidecars must come with it or SQLite sees a database newer than its journal.
_FILES: tuple[tuple[str, str], ...] = (
    ("config.toml", "config.toml"),
    ("state.ini", "state.ini"),
    (LEGACY_DATABASE_NAME, DATABASE_NAME),
    (f"{LEGACY_DATABASE_NAME}-wal", f"{DATABASE_NAME}-wal"),
    (f"{LEGACY_DATABASE_NAME}-shm", f"{DATABASE_NAME}-shm"),
)


def _appdata_dir(slug: str) -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / slug
    return Path.home() / f".{slug.lower()}"


def config_dir() -> Path:
    """Where config.toml and the SQLite database live."""
    return _appdata_dir(SLUG)


def legacy_config_dir() -> Path:
    """Where they lived when the app was called Lutin."""
    return _appdata_dir(LEGACY_SLUG)


def config_path() -> Path:
    return config_dir() / "config.toml"


def database_path() -> Path:
    return config_dir() / DATABASE_NAME


def state_path() -> Path:
    """The QSettings file holding the avatar's last position."""
    return config_dir() / "state.ini"


@dataclass
class Migration:
    """What one migration attempt did, for the notification and the tests."""

    copied: list[str] = field(default_factory=list)
    #: Files that were already present at the destination, so left alone.
    kept: list[str] = field(default_factory=list)
    #: Reason we did nothing at all, when that is the case.
    skipped: str = ""
    failures: list[str] = field(default_factory=list)

    @property
    def happened(self) -> bool:
        return bool(self.copied)

    def summary(self) -> str:
        """One French line for the tray notification, or empty if nothing moved."""
        if not self.copied:
            return ""
        count = len(self.copied)
        plural = "s" if count > 1 else ""
        return (
            f"{count} fichier{plural} récupéré{plural} depuis l'ancien dossier "
            f"{LEGACY_SLUG}. L'original n'a pas été touché."
        )


def migrate_legacy_data(
    legacy: Path | None = None, current: Path | None = None
) -> Migration:
    """Copy the old Lutin folder's contents into the new one, once.

    Safe to call on every start: the marker makes it a no-op afterwards.
    """
    source = legacy if legacy is not None else legacy_config_dir()
    target = current if current is not None else config_dir()

    if source == target:
        return Migration(skipped="same folder")
    if not source.is_dir():
        return Migration(skipped="no legacy folder")
    if (source / MARKER_NAME).exists():
        return Migration(skipped="already migrated")

    result = Migration()
    present = [(old, new) for old, new in _FILES if (source / old).is_file()]
    if not present:
        # An empty or already-emptied folder still gets a marker, so we stop
        # looking at it on every start.
        _write_marker(source, result)
        return Migration(skipped="nothing to copy")

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.failures.append(f"{target}: {exc}")
        return result

    for old, new in present:
        destination = target / new
        if destination.exists():
            result.kept.append(new)
            continue
        try:
            shutil.copy2(source / old, destination)
        except OSError as exc:
            result.failures.append(f"{old}: {exc}")
        else:
            result.copied.append(new)

    # Only claim the migration is done if nothing failed; otherwise we want to
    # try again next start rather than strand half the data.
    if not result.failures:
        _write_marker(source, result)
    return result


def _write_marker(source: Path, result: Migration) -> None:
    try:
        (source / MARKER_NAME).write_text(
            "Contenu copié vers le nouveau dossier de Little Wizard.\n"
            "Ce dossier peut être supprimé si tout fonctionne.\n",
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover - a read-only APPDATA is absurd
        result.failures.append(f"{MARKER_NAME}: {exc}")
