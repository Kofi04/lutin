"""Adding and removing Little Wizard's hooks in ~/.claude/settings.json.

This edits a file the user owns and that Claude Code depends on, so the rules
are strict, and they are coucou's: back it up, *merge* rather than replace,
show the diff before writing, and remove only our own entries on uninstall.

`merge_hooks` and `remove_hooks` are pure functions on plain dicts so the
careful part is unit-tested without touching the real file.
"""

from __future__ import annotations

import copy
import difflib
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: Marks an entry as ours. Uninstall removes exactly the entries whose command
#: line mentions this, and nothing else.
HOOK_SCRIPT_NAME = "wizard_hook.py"

#: The same script, frozen on its own by PyInstaller for the installed app,
#: which has no Python to run a .py with. Standard library only: it starts
#: without loading anything of the core (PySide6, the SDK).
HOOK_EXE_NAME = "wizard-hook.exe"

#: Names we have used in the past. A machine that installed the hooks when the
#: app was called "Lutin" has `lutin_hook.py` in its settings.json, and that
#: entry now points at a script that no longer exists: every tool call would
#: spawn a process that fails. Recognising the old name is what lets
#: "uninstall" clean it up, and what makes "install" replace it instead of
#: stacking a second, broken entry beside the new one.
LEGACY_HOOK_SCRIPT_NAMES = ("lutin_hook.py",)

#: Every marker that means "this entry belongs to us".
OWNED_SCRIPT_NAMES = (HOOK_SCRIPT_NAME, HOOK_EXE_NAME, *LEGACY_HOOK_SCRIPT_NAMES)

#: Fired in the background: they can never block or delay a session.
OBSERVED_EVENTS = (
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
    "Notification",
)

#: The one event we answer, so it has to block until the user decides.
DECIDING_EVENT = "PermissionRequest"

#: Events that match on a tool name and therefore need a matcher.
_TOOL_EVENTS = {
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
}

#: Comfortably above the app's own permission timeout, comfortably below
#: Claude Code's 600s default for command hooks.
DECISION_TIMEOUT_S = 150


def settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))  # PyInstaller


def hook_script_path() -> Path | None:
    """Where wizard_hook.py lives; None in the installed app (it is an .exe)."""
    if _frozen():
        return None
    return Path(__file__).resolve().parents[3] / "hooks" / HOOK_SCRIPT_NAME


def launcher_path() -> Path:
    """A real .exe: Windows exec-form hooks cannot spawn .cmd or .bat shims.

    From source, the venv's pythonw.exe runs the script. Installed, the hook
    is its own exe, next to the core's folder: <app>/hook/wizard-hook.exe
    beside <app>/core/wizard-core.exe (the Tauri bundle's resources).
    """
    executable = Path(sys.executable)
    if _frozen():
        return executable.parent.parent / "hook" / HOOK_EXE_NAME
    windowed = executable.with_name("pythonw.exe")
    return windowed if windowed.exists() else executable


@dataclass(frozen=True)
class InstallPlan:
    path: Path
    diff: str
    before: dict
    after: dict

    @property
    def changed(self) -> bool:
        return self.before != self.after


def _entry(event: str, launcher: str, script: str, blocking: bool) -> dict:
    """One hook entry, in exec form.

    Exec form (`args` present) skips the shell entirely, which matters because
    PreToolUse fires on every single tool call.
    """
    hook: dict = {
        "type": "command",
        "command": launcher,
        # No script for the frozen hook: the exe is the script.
        "args": [script, event] if script else [event],
    }
    if blocking:
        hook["timeout"] = DECISION_TIMEOUT_S
    else:
        # Observational: never hold up the session, whatever Little Wizard is doing.
        hook["async"] = True

    group: dict = {"hooks": [hook]}
    if event in _TOOL_EVENTS:
        group["matcher"] = "*"
    return group


def build_hooks(launcher: str | None = None, script: str | None = None) -> dict:
    """The `hooks` block Little Wizard wants, keyed by event name."""
    launcher = launcher or str(launcher_path())
    if script is None:
        default = hook_script_path()
        script = str(default) if default is not None else ""

    hooks = {
        event: [_entry(event, launcher, script, blocking=False)]
        for event in OBSERVED_EVENTS
    }
    hooks[DECIDING_EVENT] = [_entry(DECIDING_EVENT, launcher, script, blocking=True)]
    return hooks


def _is_ours(group: dict) -> bool:
    for hook in group.get("hooks", []) or []:
        if not isinstance(hook, dict):
            continue
        args = " ".join(map(str, hook.get("args", []) or []))
        blob = f"{hook.get('command', '')} {args}"
        if any(name in blob for name in OWNED_SCRIPT_NAMES):
            return True
    return False


def remove_hooks(settings: dict) -> dict:
    """Drop only Little Wizard's entries, leaving every other hook untouched."""
    result = copy.deepcopy(settings)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        return result

    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        kept = [g for g in groups if not (isinstance(g, dict) and _is_ours(g))]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]

    if not hooks:
        del result["hooks"]
    return result


def merge_hooks(settings: dict, ours: dict) -> dict:
    """Add our entries next to whatever is already there.

    Our previous entries are replaced where they stand, so re-running the
    installer after moving the project updates the paths instead of stacking
    duplicates. In place, not moved to the end: with another tool's hooks on
    the same events (Coucou, say), moving ours behind them on every install
    meant the plan was never "nothing to do", and its diff, all reordering,
    hid whether the hooks were installed at all.
    """
    result = copy.deepcopy(settings)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        result["hooks"] = hooks

    for event, groups in list(hooks.items()):
        if event not in ours and isinstance(groups, list):
            # An event we no longer use: drop our stale entries, keep the rest.
            kept = [g for g in groups if not (isinstance(g, dict) and _is_ours(g))]
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]

    for event, wanted in ours.items():
        existing = hooks.get(event)
        if not isinstance(existing, list):
            existing = []
        merged: list = []
        placed = False
        for group in existing:
            if isinstance(group, dict) and _is_ours(group):
                if not placed:
                    merged.extend(copy.deepcopy(wanted))
                    placed = True
                continue
            merged.append(group)
        if not placed:
            merged.extend(copy.deepcopy(wanted))
        hooks[event] = merged
    return result


def _render(settings: dict) -> str:
    return json.dumps(settings, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def diff(before: dict, after: dict, path: Path) -> str:
    return "".join(
        difflib.unified_diff(
            _render(before).splitlines(keepends=True),
            _render(after).splitlines(keepends=True),
            fromfile=f"{path} (avant)",
            tofile=f"{path} (après)",
        )
    )


def read_settings(path: Path | None = None) -> dict:
    target = path or settings_path()
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def plan_install(path: Path | None = None) -> InstallPlan:
    target = path or settings_path()
    before = read_settings(target)
    after = merge_hooks(before, build_hooks())
    return InstallPlan(target, diff(before, after, target), before, after)


def plan_uninstall(path: Path | None = None) -> InstallPlan:
    target = path or settings_path()
    before = read_settings(target)
    after = remove_hooks(before)
    return InstallPlan(target, diff(before, after, target), before, after)


def backup(path: Path) -> Path | None:
    """Copy settings.json aside before touching it."""
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = path.with_name(f"{path.name}.bak-{stamp}")
    destination.write_bytes(path.read_bytes())
    return destination


def apply(plan: InstallPlan) -> Path | None:
    """Write the plan, after backing up. Returns the backup path."""
    saved = backup(plan.path)
    plan.path.parent.mkdir(parents=True, exist_ok=True)
    plan.path.write_text(_render(plan.after), encoding="utf-8")
    return saved


def is_installed(path: Path | None = None) -> bool:
    hooks = read_settings(path).get("hooks")
    if not isinstance(hooks, dict):
        return False
    return any(
        isinstance(group, dict) and _is_ours(group)
        for groups in hooks.values()
        if isinstance(groups, list)
        for group in groups
    )


def is_stale(path: Path | None = None) -> bool:
    """True when our hooks are installed but point somewhere that no longer works.

    Two ways that happens: the entry was written under the app's old name, or
    the project folder moved (or the app was uninstalled) and the recorded
    script or exe is gone. Either way
    Claude Code would spawn a process that dies on every tool call. The caller
    needs to know, because the fix is to *re-install* (which replaces the
    entries) and a menu that only offers "uninstall" leaves the user stuck.
    """
    hooks = read_settings(path).get("hooks")
    if not isinstance(hooks, dict):
        return False
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict) or not _is_ours(group):
                continue
            for hook in group.get("hooks", []) or []:
                if not isinstance(hook, dict):
                    continue
                args = [str(item) for item in hook.get("args", []) or []]
                blob = f"{hook.get('command', '')} {' '.join(args)}"
                if any(name in blob for name in LEGACY_HOOK_SCRIPT_NAMES):
                    return True
                script = next(
                    (arg for arg in args if arg.endswith(HOOK_SCRIPT_NAME)), ""
                )
                if script and not Path(script).exists():
                    return True
                command = str(hook.get("command", ""))
                if command.endswith(HOOK_EXE_NAME) and not Path(command).exists():
                    return True
    return False


def summarise_backup(path) -> str:
    """The backup made before writing, in one line for a notification."""
    if path is None:
        return "Aucune sauvegarde nécessaire (le fichier n'existait pas)."
    return f"Sauvegarde : {path.name}"
