"""Launching apps, folders, documents and URLs from the avatar menu.

Security note: nothing here ever goes through a shell. `subprocess.Popen` is
always given an argument *list*, and the no-argument path uses
`os.startfile` (ShellExecute), which takes the target as a single opaque
string. That means a launcher entry cannot smuggle in `&& rm -rf ...`, even
though config.toml is a file the user edits freely.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import LauncherEntry


class LaunchError(RuntimeError):
    """Raised when a launcher entry could not be started."""


def _resolve_working_dir(entry: LauncherEntry) -> str | None:
    if not entry.working_dir:
        return None
    path = Path(os.path.expandvars(entry.working_dir)).expanduser()
    if not path.is_dir():
        raise LaunchError(f"le dossier working_dir n'existe pas : {path}")
    return str(path)


def launch(entry: LauncherEntry) -> None:
    """Start a launcher entry, raising LaunchError with a readable message."""
    target = os.path.expandvars(entry.target).strip()
    if not target:
        raise LaunchError(f"cible vide pour {entry.label!r}")

    cwd = _resolve_working_dir(entry)

    # os.startfile is the right tool when we have nothing to add: it asks the
    # shell to open the target, which covers executables, documents, folders,
    # URLs and shell: monikers alike. It has no cwd parameter though, so any
    # entry with args or a working_dir goes through Popen instead.
    if not entry.args and cwd is None:
        try:
            os.startfile(target)  # type: ignore[attr-defined]  # Windows-only
            return
        except OSError as exc:
            raise LaunchError(f"impossible d'ouvrir {target!r} ({exc})") from exc
        except AttributeError as exc:  # pragma: no cover - non-Windows
            raise LaunchError("os.startfile n'existe que sous Windows") from exc

    executable = shutil.which(target) or target
    try:
        subprocess.Popen(
            [executable, *entry.args],
            cwd=cwd,
            close_fds=True,
            # Detach so the avatar is not the parent of long-lived apps and
            # closing it never takes them down with it.
            creationflags=_detached_flags(),
        )
    except (OSError, ValueError) as exc:
        raise LaunchError(f"impossible de lancer {target!r} ({exc})") from exc


def _detached_flags() -> int:
    if sys.platform != "win32":  # pragma: no cover - non-Windows
        return 0
    # Only a new process group: it stops our Ctrl+C from reaching the child
    # without hiding anything. CREATE_NO_WINDOW is deliberately *not* set,
    # because it would make a launcher entry for a console script run
    # invisibly, which reads as "nothing happened".
    return subprocess.CREATE_NEW_PROCESS_GROUP
