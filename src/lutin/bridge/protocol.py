"""Framing for the hook <-> app pipe.

Four bytes of big-endian length, then UTF-8 JSON. A named pipe is a byte
stream, so without a length prefix two events written back to back would arrive
as one unparseable blob.

`hooks/lutin_hook.py` repeats these few lines instead of importing them. The
hook has to start in milliseconds and must keep working when the app is broken,
so it stays free of any dependency on this package.
"""

from __future__ import annotations

import json
import struct

#: Named pipe QLocalServer listens on. QLocalServer maps this to
#: \\.\pipe\<PIPE_NAME> on Windows.
PIPE_NAME = "Lutin-hooks"

_HEADER = struct.Struct(">I")
HEADER_SIZE = _HEADER.size

#: Refuse anything larger than this. Hook payloads are small; a huge length
#: prefix means a corrupted stream or something that is not our hook.
MAX_FRAME = 4 * 1024 * 1024


def encode(message: dict) -> bytes:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    return _HEADER.pack(len(body)) + body


def frame_length(header: bytes) -> int:
    """Payload length from a 4-byte header, validated."""
    if len(header) < HEADER_SIZE:
        raise ValueError("short header")
    (length,) = _HEADER.unpack(header[:HEADER_SIZE])
    if length <= 0 or length > MAX_FRAME:
        raise ValueError(f"implausible frame length: {length}")
    return length


def decode(body: bytes) -> dict:
    message = json.loads(body.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("frame is not a JSON object")
    return message
