"""The methods the Tauri UI may call: only those registered, failures answered."""

from __future__ import annotations

import pytest

from wizard.rpc import Rpc, RpcError


def test_a_registered_method_runs_with_its_params():
    rpc = Rpc()
    rpc.register("notes.add", lambda params: {"id": len(params["body"])})
    assert rpc.call("notes.add", {"body": "abc"}) == {"id": 3}


def test_nothing_else_exists():
    with pytest.raises(RpcError) as caught:
        Rpc().call("os.system", {"cmd": "format c:"})
    assert caught.value.code == "unknown_method"


def test_a_missing_param_is_said_plainly():
    rpc = Rpc()
    rpc.register("notes.add", lambda params: {"id": params["body"]})
    with pytest.raises(RpcError) as caught:
        rpc.call("notes.add", {})
    assert caught.value.code == "bad_params"


def test_a_refusal_keeps_its_message_for_the_user():
    rpc = Rpc()

    def refuse(params):
        raise RpcError("invalid", "Raccourci déjà pris")

    rpc.register("settings.write", refuse)
    with pytest.raises(RpcError) as caught:
        rpc.call("settings.write", {})
    assert (caught.value.code, caught.value.message) == ("invalid", "Raccourci déjà pris")


def test_a_bug_is_answered_as_failed_not_raised_raw():
    rpc = Rpc()
    rpc.register("boom", lambda params: 1 / 0)
    with pytest.raises(RpcError) as caught:
        rpc.call("boom", None)
    assert caught.value.code == "failed"


def test_none_becomes_an_empty_answer():
    rpc = Rpc()
    rpc.register("noop", lambda params: None)
    assert rpc.call("noop", {}) == {}


def test_a_name_cannot_be_registered_twice():
    rpc = Rpc()
    rpc.register("a", lambda p: {})
    with pytest.raises(ValueError):
        rpc.register("a", lambda p: {})
