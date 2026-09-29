"""User configuration, read from a TOML file with tomllib (stdlib).

The config is deliberately read-only from the app's point of view: you edit
config.toml by hand, which keeps the format stable and avoids the app ever
rewriting (and reformatting) a file you own. Unknown keys are ignored and bad
values are reported through `Config.warnings` rather than crashing at startup,
because a typo in a launcher entry should not cost you the whole avatar.
"""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .branding import SLUG


def config_dir() -> Path:
    """Where config.toml and the SQLite database live."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / SLUG
    return Path.home() / f".{SLUG.lower()}"


def config_path() -> Path:
    return config_dir() / "config.toml"


def database_path() -> Path:
    return config_dir() / "lutin.db"


DEFAULT_CONFIG_TEMPLATE = Path(__file__).resolve().parent / "config.default.toml"


@dataclass
class Appearance:
    scale: float = 1.0
    opacity: float = 0.96
    offset_x: int = 0
    offset_y: int = 0
    click_through_when_idle: bool = False


@dataclass
class Hotkeys:
    quick_note: str = "ctrl+alt+N"
    clipboard: str = "ctrl+alt+V"
    toggle_avatar: str = "ctrl+alt+A"
    launcher: str = "ctrl+alt+Space"
    capture_region: str = "ctrl+alt+S"


@dataclass
class MonitorSettings:
    enabled: bool = True
    interval_seconds: float = 3.0
    cpu_busy: float = 65.0
    cpu_stressed: float = 88.0
    ram_stressed: float = 88.0
    battery_low: int = 20


@dataclass
class ClipboardSettings:
    enabled: bool = True
    max_entries: int = 200
    max_text_length: int = 20_000


@dataclass
class LauncherEntry:
    label: str
    target: str
    args: list[str] = field(default_factory=list)
    working_dir: str | None = None


@dataclass
class Config:
    appearance: Appearance = field(default_factory=Appearance)
    hotkeys: Hotkeys = field(default_factory=Hotkeys)
    monitor: MonitorSettings = field(default_factory=MonitorSettings)
    clipboard: ClipboardSettings = field(default_factory=ClipboardSettings)
    launcher: list[LauncherEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def ensure_config_file(path: Path | None = None) -> Path:
    """Create config.toml from the bundled template on first run."""
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() and DEFAULT_CONFIG_TEMPLATE.exists():
        shutil.copyfile(DEFAULT_CONFIG_TEMPLATE, target)
    return target


def _coerce(
    raw: dict,
    key: str,
    kind: type,
    default,
    warnings: list[str],
    where: str,
):
    """Read raw[key] as `kind`, falling back to default and warning on junk."""
    if key not in raw:
        return default
    value = raw[key]
    if kind is float and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    # bool is a subclass of int, so guard the int case explicitly.
    if kind is int and isinstance(value, bool):
        pass
    elif isinstance(value, kind):
        return value
    warnings.append(
        f"{where}.{key} : attendu {kind.__name__}, reçu {value!r}"
        f" — valeur par défaut {default!r} utilisée"
    )
    return default


def _load_section(raw: dict, section: str, target, warnings: list[str]):
    """Fill a dataclass instance from a TOML table, field by field."""
    table = raw.get(section, {})
    if not isinstance(table, dict):
        warnings.append(f"[{section}] : une table était attendue, section ignorée")
        return target
    for name, current in vars(target).items():
        kind = type(current) if current is not None else str
        setattr(target, name, _coerce(table, name, kind, current, warnings, section))
    return target


def _load_launcher(raw: dict, warnings: list[str]) -> list[LauncherEntry]:
    entries: list[LauncherEntry] = []
    items = raw.get("launcher", [])
    if not isinstance(items, list):
        warnings.append(
            "[[launcher]] : une liste de tables était attendue, section ignorée"
        )
        return entries

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            warnings.append(f"launcher[{index}] : ce n'est pas une table, ignoré")
            continue
        label = item.get("label")
        target = item.get("target")
        if not isinstance(label, str) or not isinstance(target, str) or not target:
            warnings.append(
                f"launcher[{index}] : il faut un 'label' texte et une"
                " 'target' non vide, entrée ignorée"
            )
            continue
        raw_args = item.get("args", [])
        if not isinstance(raw_args, list) or not all(
            isinstance(a, str) for a in raw_args
        ):
            warnings.append(
                f"launcher[{label}].args : des chaînes étaient attendues, ignoré"
            )
            raw_args = []
        working_dir = item.get("working_dir")
        if working_dir is not None and not isinstance(working_dir, str):
            warnings.append(
                f"launcher[{label}].working_dir : une chaîne était attendue"
            )
            working_dir = None
        entries.append(
            LauncherEntry(
                label=label, target=target, args=list(raw_args), working_dir=working_dir
            )
        )
    return entries


def load_config(path: Path | None = None) -> Config:
    """Load the config, degrading to defaults for anything malformed."""
    target = path or config_path()
    config = Config()

    if not target.exists():
        config.warnings.append(
            f"aucun fichier de configuration dans {target} — valeurs par défaut"
        )
        return config

    try:
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        config.warnings.append(
            f"lecture impossible de {target} ({exc}) — valeurs par défaut"
        )
        return config

    _load_section(raw, "appearance", config.appearance, config.warnings)
    _load_section(raw, "hotkeys", config.hotkeys, config.warnings)
    _load_section(raw, "monitor", config.monitor, config.warnings)
    _load_section(raw, "clipboard", config.clipboard, config.warnings)
    config.launcher = _load_launcher(raw, config.warnings)

    # Clamp the values where an out-of-range number would break the UI.
    config.appearance.scale = min(max(config.appearance.scale, 0.5), 4.0)
    config.appearance.opacity = min(max(config.appearance.opacity, 0.2), 1.0)
    config.monitor.interval_seconds = min(
        max(config.monitor.interval_seconds, 0.5), 60.0
    )
    config.clipboard.max_entries = min(max(config.clipboard.max_entries, 10), 5000)

    return config
