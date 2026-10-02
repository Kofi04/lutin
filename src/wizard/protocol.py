"""The messages exchanged with the Tauri UI, checked on the way in and out.

The list of messages is not written here: it lives in `protocol_messages.json`,
which the TypeScript side reads too. Two hand-kept copies of a protocol drift
apart; one file read by both cannot.

The envelope is `{"type": ..., "id": ..., "payload": {...}}`. `id` is optional:
events have none, requests carry one and get it back on their `reply`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any

#: Bumped whenever a message changes shape; `hello` must carry the same number.
PROTOCOL_VERSION = 1

CORE = "core"
UI = "ui"

_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    # bool is an int in Python; JSON true is not a number. And 2.0 is an
    # integer, as it is for JavaScript, which cannot tell it from 2.
    "integer": lambda v: (
        (isinstance(v, int) and not isinstance(v, bool))
        or (isinstance(v, float) and v.is_integer())
    ),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
}


class ProtocolError(ValueError):
    """A message that does not follow the protocol.

    `code` is short and stable, for the `error` reply; the text is for humans.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Message:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str | None = None


@cache
def spec() -> dict[str, Any]:
    """The message list, as `protocol_messages.json` defines it."""
    text = (
        resources.files(__package__)
        .joinpath("protocol_messages.json")
        .read_text(encoding="utf-8")
    )
    data = json.loads(text)
    if data.get("version") != PROTOCOL_VERSION:
        raise RuntimeError("protocol_messages.json and PROTOCOL_VERSION disagree")
    return data["messages"]


def message_types(sender: str | None = None) -> list[str]:
    """Every message type, or only those `sender` ("core" or "ui") may send."""
    return [
        name
        for name, entry in spec().items()
        if sender is None or entry["from"] == sender
    ]


def validate(type_: str, payload: Any, sender: str) -> None:
    """Raise ProtocolError unless `payload` is a valid `type_` from `sender`."""
    entry = spec().get(type_)
    if entry is None:
        raise ProtocolError("unknown_type", f"unknown message type: {type_!r}")
    if entry["from"] != sender:
        raise ProtocolError("wrong_direction", f"{type_} is not sent by the {sender}")
    if not isinstance(payload, dict):
        raise ProtocolError("bad_payload", f"{type_}: payload must be an object")

    fields: dict[str, Any] = entry["payload"]
    extra = sorted(set(payload) - set(fields))
    if extra:
        raise ProtocolError("bad_payload", f"{type_}: unknown field(s) {extra}")

    for name, kind in fields.items():
        optional = isinstance(kind, str) and kind.endswith("?")
        if name not in payload or payload[name] is None:
            if optional:
                continue
            raise ProtocolError("bad_payload", f"{type_}: missing field {name!r}")
        value = payload[name]
        if isinstance(kind, list):
            if value not in kind:
                raise ProtocolError(
                    "bad_payload", f"{type_}.{name}: {value!r} is not one of {kind}"
                )
        elif not _TYPE_CHECKS[kind.rstrip("?")](value):
            raise ProtocolError(
                "bad_payload", f"{type_}.{name}: expected {kind.rstrip('?')}"
            )


def encode(
    type_: str, payload: dict[str, Any] | None = None, id: str | None = None
) -> str:
    """A core message, validated: sending a malformed one is our bug, not the UI's."""
    payload = {} if payload is None else payload
    validate(type_, payload, CORE)
    envelope: dict[str, Any] = {"type": type_, "payload": payload}
    if id is not None:
        envelope["id"] = id
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))


def decode(text: str, sender: str = UI) -> Message:
    """Parse and validate one message received from `sender`."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise ProtocolError("bad_json", f"not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise ProtocolError("bad_envelope", "a message must be a JSON object")

    extra = sorted(set(data) - {"type", "id", "payload"})
    if extra:
        raise ProtocolError("bad_envelope", f"unknown envelope field(s) {extra}")
    type_ = data.get("type")
    if not isinstance(type_, str):
        raise ProtocolError("bad_envelope", "missing or invalid 'type'")
    message_id = data.get("id")
    if message_id is not None and not isinstance(message_id, str):
        raise ProtocolError("bad_envelope", "'id' must be a string")
    payload = data.get("payload", {})

    validate(type_, payload, sender)
    return Message(type_, payload, message_id)
