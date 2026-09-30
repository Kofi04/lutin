"""Claude Code hook handler: forward one event to Little Wizard, optionally wait.

Run as `pythonw.exe wizard_hook.py <EventName>`. Standard library only, and no
import from the `wizard` package: this runs on every tool call, must start in
milliseconds, and must keep working when the app is broken or absent.

The one rule that matters: **Claude Code is never blocked.** Every failure path
exits 0 with no output, which leaves the normal flow untouched. Only an
explicit user decision ever writes a decision object.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import threading
import time

PIPE_PATH = r"\\.\pipe\LittleWizard-hooks"
HEADER = struct.Struct(">I")

#: How long to wait for the app to accept the connection. Past this the app is
#: not running (or is wedged) and the terminal takes over.
CONNECT_TIMEOUT_S = 0.4

#: Hard ceiling on the whole process. Claude Code's own command-hook timeout
#: defaults to 600s; we stop well before that so a stuck hook can never be the
#: reason a session hangs.
DEFAULT_DEADLINE_S = 130.0

#: Events where we wait for the user to decide. Everything else is fire and
#: forget (and registered with "async": true, so it never blocks at all).
BLOCKING_EVENTS = {"PermissionRequest"}


def _bail() -> None:
    """Leave without a decision: Claude Code carries on as if we did not exist."""
    os._exit(0)


def _arm_watchdog(seconds: float) -> None:
    """Guarantee an exit even if a read blocks forever."""

    def fire() -> None:
        time.sleep(seconds)
        _bail()

    threading.Thread(target=fire, daemon=True).start()


def _connect(deadline: float):
    """Open the named pipe, retrying while the server is busy."""
    while time.monotonic() < deadline:
        try:
            return open(PIPE_PATH, "r+b", buffering=0)
        except OSError:
            time.sleep(0.02)
    return None


def _send(pipe, message: dict) -> None:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    pipe.write(HEADER.pack(len(body)) + body)
    pipe.flush()


def _receive(pipe) -> dict | None:
    header = pipe.read(HEADER.size)
    if not header or len(header) < HEADER.size:
        return None
    (length,) = HEADER.unpack(header)
    if length <= 0 or length > 4 * 1024 * 1024:
        return None

    chunks, remaining = [], length
    while remaining > 0:
        chunk = pipe.read(remaining)
        if not chunk:
            return None
        chunks.append(chunk)
        remaining -= len(chunk)
    try:
        message = json.loads(b"".join(chunks).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return message if isinstance(message, dict) else None


def _terminal_context() -> dict:
    """Enough to jump back to the session's window later."""
    return {
        "term_program": os.environ.get("TERM_PROGRAM", ""),
        "wt_session": os.environ.get("WT_SESSION", ""),
        "session_name": os.environ.get("SESSIONNAME", ""),
        "pid": os.getppid(),
    }


def _decision_output(event: str, decision: str) -> dict | None:
    """Translate the user's answer into the shape Claude Code expects."""
    if decision == "allow":
        body = {"behavior": "allow"}
    elif decision == "deny":
        body = {
            "behavior": "deny",
            "message": "Refusé depuis Little Wizard.",
            "interrupt": False,
        }
    else:
        return None  # "defer" and anything unknown: stay out of the way
    return {"hookSpecificOutput": {"hookEventName": event, "decision": body}}


def main() -> None:
    event = sys.argv[1] if len(sys.argv) > 1 else "Unknown"

    # Sessions Little Wizard started itself already answer through the SDK's permission
    # callback. Reporting them again would double every prompt.
    if os.environ.get("WIZARD_OWN_SESSION"):
        _bail()

    blocking = event in BLOCKING_EVENTS
    _arm_watchdog(DEFAULT_DEADLINE_S if blocking else 5.0)

    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        _bail()

    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}

    pipe = _connect(time.monotonic() + CONNECT_TIMEOUT_S)
    if pipe is None:
        _bail()

    try:
        _send(
            pipe,
            {
                "event": event,
                "payload": payload,
                "terminal": _terminal_context(),
                "wants_decision": blocking,
            },
        )
        if not blocking:
            _bail()

        answer = _receive(pipe)
    except OSError:
        _bail()

    if not answer:
        _bail()

    output = _decision_output(event, str(answer.get("decision", "")))
    if output is not None:
        sys.stdout.write(json.dumps(output, ensure_ascii=False))
        sys.stdout.flush()
    _bail()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        # Nothing this script can hit is worth blocking a Claude Code session.
        _bail()
