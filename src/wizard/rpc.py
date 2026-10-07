"""What the Tauri UI may ask of the core: a list of methods, and nothing else.

A window sends `request {method, params}` with an id; the core runs the
method of that name and answers `reply {ok, data}` with the same id, or
`reply {ok: false, error, message}`. Only registered methods exist: the UI
cannot reach anything the core did not put here on purpose.

Methods take the request's params (a dict) and return a dict. They raise
RpcError for a refusal the user should read (French message), anything else
for a bug, which is logged and answered as "failed".
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

Method = Callable[[dict[str, Any]], dict[str, Any] | None]


class RpcError(Exception):
    """A refusal, with a code for the UI and a message for the user."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Rpc:
    def __init__(self) -> None:
        self._methods: dict[str, Method] = {}

    def register(self, name: str, method: Method) -> None:
        if name in self._methods:
            raise ValueError(f"method registered twice: {name}")
        self._methods[name] = method

    @property
    def names(self) -> list[str]:
        return sorted(self._methods)

    def call(self, name: str, params: dict[str, Any] | None) -> dict[str, Any]:
        """Run a method; RpcError for every failure, ready to answer."""
        method = self._methods.get(name)
        if method is None:
            raise RpcError("unknown_method", f"Méthode inconnue : {name}")
        try:
            result = method(params or {})
        except RpcError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            # A missing or malformed parameter: the UI's bug, said plainly.
            raise RpcError(
                "bad_params", f"{name} : paramètres invalides ({exc})"
            ) from exc
        except Exception as exc:
            log.exception("rpc %s failed", name)
            raise RpcError("failed", f"{name} a échoué : {exc}") from exc
        return result if result is not None else {}
