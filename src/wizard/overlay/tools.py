"""The on-screen guidance tools Claude can call: point_at, highlight, show_steps,
clear_overlay.

They run in-process, as an SDK MCP server, on the Claude worker thread. They
never touch a widget: each one maps Claude's image coordinates to the desktop
(`mapping.py`, the only place that does it) and emits a signal on a bridge
object that lives on the GUI thread. Qt queues a signal crossing threads, so
the overlay is always drawn on the thread that owns it.

The tools only work against a capture that came from the screen. A dropped
photo has nowhere on the desktop to point at, so the tools say so instead of
drawing an arrow at an arbitrary spot — a confidently wrong pointer is worse
than none.

They are display-only and cannot change anything, so they are pre-approved:
asking the user "may Claude draw an arrow?" would be absurd.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from .mapping import (
    CaptureFrame,
    MappingError,
    image_rect_to_logical,
    image_to_logical,
)
from .scene import Highlight, Pointer, Step

#: The MCP server name. Tools are exposed to Claude as mcp__<SERVER>__<tool>.
SERVER = "wizard"

TOOL_NAMES = ("point_at", "highlight", "show_steps", "clear_overlay", "set_reminder")

#: Fully qualified, for `allowed_tools`.
QUALIFIED = tuple(f"mcp__{SERVER}__{name}" for name in TOOL_NAMES)

#: Told to Claude so it knows the tools exist and how to use them well.
PROMPT_HINT = (
    "Tu peux montrer des choses directement sur l'écran de l'utilisateur avec "
    "les outils point_at, highlight et show_steps. Les coordonnées sont en "
    "pixels de la dernière capture qu'on t'a montrée, origine en haut à gauche. "
    "Utilise-les quand une réponse gagne à être montrée plutôt que décrite "
    "(« clique ici », « ce bouton-là »). Pour une procédure en plusieurs étapes, "
    "préfère show_steps. Ces outils ne marchent que sur une capture d'écran, "
    "pas sur une image déposée."
)


class OverlayBridge(QObject):
    """Lives on the GUI thread; the tools emit its signals from the worker."""

    point_requested = Signal(float, float, str)
    highlight_requested = Signal(float, float, float, float, str, str)
    steps_requested = Signal(object)  # list[Step]
    clear_requested = Signal()
    #: (seconds, label) — a reminder Claude was asked to set.
    reminder_requested = Signal(int, str)


def _text(message: str, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": message}], "is_error": error}


_NO_SCREEN = (
    "Aucune capture d'écran dans cette conversation : je ne peux rien montrer "
    "à l'écran. Demande à l'utilisateur de montrer une zone ou une fenêtre."
)


def _frame_or_error(current_frame: Callable[[], CaptureFrame | None]):
    frame = current_frame()
    if frame is None:
        return None, _text(_NO_SCREEN, error=True)
    return frame, None


def build_handlers(
    bridge: OverlayBridge, current_frame: Callable[[], CaptureFrame | None]
) -> dict:
    """The four tool bodies, as plain async functions.

    Kept separate from the MCP registration so they can be tested by calling
    them directly, without an SDK server in the way.
    """

    async def point_at(args: dict) -> dict:
        frame, error = _frame_or_error(current_frame)
        if error:
            return error
        try:
            point = image_to_logical(frame, float(args["x"]), float(args["y"]))
        except (MappingError, KeyError, TypeError, ValueError) as exc:
            return _text(f"Coordonnées invalides : {exc}", error=True)
        bridge.point_requested.emit(point.x, point.y, str(args.get("label", "")))
        note = " (ramené sur le bord de la capture)" if point.clamped else ""
        return _text(f"Flèche affichée{note}.")

    async def highlight(args: dict) -> dict:
        frame, error = _frame_or_error(current_frame)
        if error:
            return error
        try:
            rect = image_rect_to_logical(
                frame,
                float(args["x"]),
                float(args["y"]),
                float(args["width"]),
                float(args["height"]),
            )
        except (MappingError, KeyError, TypeError, ValueError) as exc:
            return _text(f"Zone invalide : {exc}", error=True)
        shape = args.get("shape", "rect")
        if shape not in ("rect", "ellipse"):
            shape = "rect"
        bridge.highlight_requested.emit(
            rect.left,
            rect.top,
            rect.width,
            rect.height,
            str(args.get("label", "")),
            shape,
        )
        return _text("Zone mise en évidence.")

    async def show_steps(args: dict) -> dict:
        frame, error = _frame_or_error(current_frame)
        if error:
            return error
        raw = args.get("steps") or []
        steps: list[Step] = []
        problems: list[str] = []
        for index, entry in enumerate(raw, start=1):
            text = str(entry.get("text", "")).strip()
            if not text:
                problems.append(f"étape {index} sans texte, ignorée")
                continue
            steps.append(Step(text, _target(frame, entry, index, problems)))
        if not steps:
            return _text("Aucune étape exploitable.", error=True)
        bridge.steps_requested.emit(steps)
        plural = "s" if len(steps) > 1 else ""
        summary = f"Tutoriel de {len(steps)} étape{plural} affiché."
        if problems:
            summary += " " + "; ".join(problems) + "."
        return _text(summary)

    async def clear_overlay(args: dict) -> dict:
        bridge.clear_requested.emit()
        return _text("Écran nettoyé.")

    async def set_reminder(args: dict) -> dict:
        try:
            seconds = round(float(args["minutes"]) * 60)
        except (KeyError, TypeError, ValueError):
            return _text("Durée invalide.", error=True)
        if seconds < 1 or seconds > 7 * 24 * 3600:
            return _text("La durée doit aller d'une seconde à une semaine.", error=True)
        label = str(args.get("label", "")).strip()[:200] or "Rappel"
        bridge.reminder_requested.emit(seconds, label)
        # Said back to Claude so it can say it to the user: these do not
        # survive closing the app.
        return _text(
            "Rappel programmé. Il est gardé en mémoire : il sera perdu si "
            "l'application est fermée avant."
        )

    return {
        "point_at": point_at,
        "highlight": highlight,
        "show_steps": show_steps,
        "clear_overlay": clear_overlay,
        "set_reminder": set_reminder,
    }


def _target(frame, entry: dict, index: int, problems: list[str]):
    """Where one tutorial step points, or None for a text-only step."""
    try:
        if all(key in entry for key in ("width", "height", "x", "y")):
            rect = image_rect_to_logical(
                frame,
                float(entry["x"]),
                float(entry["y"]),
                float(entry["width"]),
                float(entry["height"]),
            )
            return Highlight(rect.left, rect.top, rect.width, rect.height)
        if "x" in entry and "y" in entry:
            point = image_to_logical(frame, float(entry["x"]), float(entry["y"]))
            return Pointer(point.x, point.y)
    except (MappingError, TypeError, ValueError) as exc:
        problems.append(f"étape {index} : position ignorée ({exc})")
    return None


# JSON Schemas, so optional fields really are optional and the SDK validates
# arguments before our code ever sees them.
_POINT_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {"type": "number", "description": "Abscisse, en pixels de la capture."},
        "y": {"type": "number", "description": "Ordonnée, en pixels de la capture."},
        "label": {"type": "string", "description": "Court texte affiché à côté."},
    },
    "required": ["x", "y"],
}

_HIGHLIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {"type": "number"},
        "y": {"type": "number"},
        "width": {"type": "number"},
        "height": {"type": "number"},
        "label": {"type": "string"},
        "shape": {"type": "string", "enum": ["rect", "ellipse"]},
    },
    "required": ["x", "y", "width", "height"],
}

_STEPS_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "width": {"type": "number"},
                    "height": {"type": "number"},
                },
                "required": ["text"],
            },
        }
    },
    "required": ["steps"],
}


def build_server(bridge: OverlayBridge, current_frame):
    """The SDK MCP server config to put in ClaudeAgentOptions.mcp_servers."""
    from claude_agent_sdk import create_sdk_mcp_server, tool

    handlers = build_handlers(bridge, current_frame)
    tools = [
        tool(
            "point_at",
            "Affiche une flèche sur l'écran de l'utilisateur, pointant un endroit "
            "de la dernière capture d'écran.",
            _POINT_SCHEMA,
        )(handlers["point_at"]),
        tool(
            "highlight",
            "Encadre une zone de la dernière capture d'écran et assombrit "
            "légèrement le reste de l'écran.",
            _HIGHLIGHT_SCHEMA,
        )(handlers["highlight"]),
        tool(
            "show_steps",
            "Affiche un tutoriel pas à pas sur l'écran : une étape à la fois, "
            "avec Suivant / Précédent. Chaque étape peut pointer un endroit "
            "(x, y) ou encadrer une zone (x, y, width, height).",
            _STEPS_SCHEMA,
        )(handlers["show_steps"]),
        tool(
            "clear_overlay",
            "Efface tout ce qui est affiché sur l'écran.",
            {"type": "object", "properties": {}},
        )(handlers["clear_overlay"]),
        tool(
            "set_reminder",
            "Programme un rappel pour l'utilisateur dans un certain nombre de "
            "minutes (une notification s'affichera). Gardé en mémoire seulement : "
            "perdu si l'application est fermée.",
            {
                "type": "object",
                "properties": {
                    "minutes": {"type": "number", "exclusiveMinimum": 0},
                    "label": {"type": "string"},
                },
                "required": ["minutes"],
            },
        )(handlers["set_reminder"]),
    ]
    return create_sdk_mcp_server(SERVER, tools=tools)
