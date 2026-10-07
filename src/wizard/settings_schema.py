"""The settings a window may change, and their limits.

The one description of the Settings window's fields (labels, ranges,
hints), in the core rather than in a window: the core checks every value
it is sent against it before writing config.toml. It started as the Qt
settings window's own tables, with the same wording.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

#: The hotkeys, in the order they are shown, with their French labels.
HOTKEY_LABELS: dict[str, str] = {
    "ask_claude": "Demander à Claude",
    "capture_region": "Montrer une zone",
    "capture_screen": "Montrer tout l'écran",
    "selection_actions": "Actions sur la sélection",
    "copy_text": "Copier le texte d'une zone",
    "launcher": "Palette de commandes",
    "quick_note": "Note rapide",
    "clipboard": "Presse-papiers",
    "toggle_avatar": "Masquer / afficher le sorcier",
}


@dataclass(frozen=True)
class Field:
    tab: str
    section: str
    key: str
    label: str
    #: "bool" | "int" | "float" | "hotkey"
    kind: str
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    suffix: str = ""
    hint: str = ""

    def describe(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}


FIELDS: tuple[Field, ...] = (
    Field("Apparence", "appearance", "scale", "Taille", "float", 0.5, 4.0, 0.25),
    Field("Apparence", "appearance", "opacity", "Opacité", "float", 0.2, 1.0, 0.05),
    Field(
        "Apparence",
        "appearance",
        "click_through_when_idle",
        "Laisser les clics traverser le sorcier",
        "bool",
        hint="Utile s'il est posé sur un bouton que vous utilisez souvent.",
    ),
    *(
        Field("Raccourcis", "hotkeys", key, label, "hotkey")
        for key, label in HOTKEY_LABELS.items()
    ),
    Field("Claude", "claude", "enabled", "Activer Claude", "bool"),
    Field(
        "Claude",
        "claude",
        "prewarm",
        "Se connecter dès le lancement",
        "bool",
        hint="La première question est immédiate, au prix d'un processus Claude Code "
        "qui reste ouvert tant que l'app tourne.",
    ),
    Field(
        "Claude",
        "claude",
        "allow_actions",
        "Claude peut agir (chaque action vous est demandée)",
        "bool",
    ),
    Field(
        "Claude",
        "claude",
        "auto_approve_read_only",
        "Lecture de fichiers sans demander",
        "bool",
        hint="Read, Glob, Grep, WebFetch et WebSearch ne modifient rien, mais ils "
        "laissent Claude lire tous les fichiers que vous pouvez lire.",
    ),
    Field(
        "Claude",
        "claude",
        "permission_timeout_seconds",
        "Délai d'autorisation",
        "int",
        5,
        600,
        1,
        " s",
        "Passé ce délai sans réponse, l'action est refusée. Le silence ne vaut pas "
        "accord.",
    ),
    Field(
        "Système",
        "clipboard",
        "enabled",
        "Enregistrer l'historique du presse-papiers",
        "bool",
        hint="Tout ce que vous copiez est gardé, mots de passe compris. Désactivez-le "
        "avant de copier un secret.",
    ),
    Field(
        "Système", "clipboard", "max_entries", "Entrées conservées", "int", 10, 5000, 10
    ),
    Field(
        "Système",
        "ui",
        "exclude_from_capture",
        "Cacher mes panneaux des partages d'écran",
        "bool",
        hint="Les réponses et les fenêtres restent visibles pour vous, pas pour ceux "
        "qui voient votre écran.",
    ),
    Field(
        "Système",
        "monitor",
        "enabled",
        "Refléter la charge de la machine dans son humeur",
        "bool",
    ),
)

_BY_KEY = {(f.section, f.key): f for f in FIELDS}


class SettingError(ValueError):
    """A value the field does not accept, said in French."""


def field(section: str, key: str) -> Field:
    try:
        return _BY_KEY[(section, key)]
    except KeyError:
        raise SettingError(f"Réglage inconnu : {section}.{key}") from None


def check(section: str, key: str, value):
    """The value, of the field's own type, or SettingError."""
    f = field(section, key)
    if f.kind == "bool":
        if not isinstance(value, bool):
            raise SettingError(f"« {f.label} » attend oui ou non.")
        return value
    if f.kind == "hotkey":
        if not isinstance(value, str):
            raise SettingError(f"« {f.label} » attend un raccourci.")
        return value.strip()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SettingError(f"« {f.label} » attend un nombre.")
    if f.kind == "int":
        if value != int(value):
            raise SettingError(f"« {f.label} » attend un nombre entier.")
        value = int(value)
    else:
        value = round(float(value), 3)
    if (f.minimum is not None and value < f.minimum) or (
        f.maximum is not None and value > f.maximum
    ):
        raise SettingError(
            f"« {f.label} » doit être entre {f.minimum:g} et {f.maximum:g}."
        )
    return value
