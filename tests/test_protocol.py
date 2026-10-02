"""The protocol: the shared spec, and the fixtures both languages must agree on."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wizard import protocol
from wizard.protocol import CORE, UI, ProtocolError

FIXTURES = json.loads(
    (Path(__file__).parent / "protocol_fixtures.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", FIXTURES["valid"], ids=lambda c: c["text"][:50])
def test_valid_fixtures_decode(case):
    message = protocol.decode(case["text"], case["from"])
    assert message.type == json.loads(case["text"])["type"]


@pytest.mark.parametrize("case", FIXTURES["invalid"], ids=lambda c: c["text"][:50])
def test_invalid_fixtures_are_refused_with_their_code(case):
    with pytest.raises(ProtocolError) as caught:
        protocol.decode(case["text"], case["from"])
    assert caught.value.code == case["error"]


def test_spec_is_well_formed():
    allowed = {"string", "integer", "number", "boolean", "object", "array"}
    for name, entry in protocol.spec().items():
        assert entry["from"] in (CORE, UI), name
        for field, kind in entry["payload"].items():
            if isinstance(kind, list):
                assert kind and all(isinstance(v, str) for v in kind), (name, field)
            else:
                assert kind.rstrip("?") in allowed, (name, field)


def test_every_design_message_exists():
    """DESIGN.md section 2 lists these; the spec may add more, never fewer."""
    core = {
        "mood", "connection", "stream.start", "stream.chunk", "stream.end",
        "approval.request", "capture.preview", "selection.result",
        "sessions.update", "toast", "guide.point", "guide.highlight",
        "guide.steps", "guide.clear", "cloak.hide", "cloak.show",
    }  # fmt: skip
    ui = {
        "ask", "approval.answer", "capture.confirm", "capture.cancel",
        "selection.replace", "selection.copy", "agent.start", "agent.stop",
        "guide.done", "cloak.ack",
    }  # fmt: skip
    assert core <= set(protocol.message_types(CORE))
    assert ui <= set(protocol.message_types(UI))


def test_encode_round_trips_and_keeps_the_id():
    text = protocol.encode("reply", {"ok": True}, id="p9")
    message = protocol.decode(text, CORE)
    assert message == protocol.Message("reply", {"ok": True}, "p9")


def test_encode_keeps_accents_readable():
    text = protocol.encode("toast", {"title": "Été", "body": "", "kind": "info"})
    assert "Été" in text


def test_encode_refuses_a_malformed_core_message():
    """Sending garbage to the UI is our bug: it must fail loudly here."""
    with pytest.raises(ProtocolError):
        protocol.encode("mood", {"mood": "grumpy"})
    with pytest.raises(ProtocolError):
        protocol.encode("ask", {"text": "the UI's message, not ours"})


def test_payload_defaults_to_empty():
    assert protocol.decode('{"type":"ping"}').payload == {}


def test_integral_float_is_an_integer_like_in_javascript():
    message = protocol.decode('{"type":"agent.stop","payload":{"agent_id":2.0}}')
    assert message.payload["agent_id"] == 2
