"""Build the installer: freeze the core and the hook, then bundle with Tauri.

    .venv\\Scripts\\python.exe packaging\\build.py           # everything
    .venv\\Scripts\\python.exe packaging\\build.py --python  # the two exes only

Two PyInstaller `--onedir` builds (not `--onefile`, which unpacks itself to a
temporary folder on every start: slower, and what antivirus software flags):

- `wizard-core`: the core. A console exe, so its standard streams are always
  real (the ready line, stdin closing when Tauri goes); Tauri starts it with
  CREATE_NO_WINDOW, so no console ever shows.
- `wizard-hook`: the Claude Code hook, frozen on its own. Standard library
  only, so it starts without loading anything of the core; windowed, because
  Claude Code runs it on every tool call and a console would flash each time.

Tauri then ships both folders as resources (`core/`, `hook/`, see
tauri.conf.json) and builds an NSIS installer.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
WORK = PACKAGING / "build"
DIST = PACKAGING / "dist"
UI = ROOT / "ui"


def run(command: list[str], cwd: Path = ROOT, env: dict | None = None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True, env=env)


def data(source: Path, target: str) -> str:
    """One --add-data argument (PyInstaller wants os.pathsep between)."""
    return f"{source}{os.pathsep}{target}"


def freeze_core() -> None:
    package = ROOT / "src" / "wizard"
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--console",
            "--name",
            "wizard-core",
            "--icon",
            str(UI / "src-tauri" / "icons" / "icon.ico"),
            "--paths",
            str(ROOT / "src"),
            "--add-data",
            data(package / "config.default.toml", "wizard"),
            "--add-data",
            data(package / "protocol_messages.json", "wizard"),
            # The SDK imports its transports lazily. (Not `mcp` wholesale: its
            # CLI wants typer, which nothing here uses.)
            "--collect-submodules",
            "claude_agent_sdk",
            "--workpath",
            str(WORK),
            "--distpath",
            str(DIST),
            "--specpath",
            str(WORK),
            str(PACKAGING / "core_entry.py"),
        ]
    )


def freeze_hook() -> None:
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--windowed",
            "--name",
            "wizard-hook",
            "--workpath",
            str(WORK),
            "--distpath",
            str(DIST),
            "--specpath",
            str(WORK),
            str(ROOT / "hooks" / "wizard_hook.py"),
        ]
    )


def bundle() -> None:
    npm = shutil.which("npm")
    if npm is None:
        sys.exit("npm is needed for the Tauri build (Node 20+).")
    # One compile job at a time: the release build of the `tauri` crate in
    # parallel runs out of memory on a 4 GB machine.
    env = {**os.environ, "CARGO_BUILD_JOBS": os.environ.get("CARGO_BUILD_JOBS", "1")}
    run([npm, "run", "tauri", "build"], cwd=UI, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--python", action="store_true", help="freeze the core and the hook only"
    )
    args = parser.parse_args()

    shutil.rmtree(DIST, ignore_errors=True)
    freeze_core()
    freeze_hook()
    if not args.python:
        bundle()
        installers = sorted(
            (UI / "src-tauri" / "target" / "release" / "bundle").rglob("*.exe")
        )
        for installer in installers:
            print("installer:", installer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
