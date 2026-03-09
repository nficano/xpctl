"""Wire protocol for the TCP transport.

Mirrors the agent's framing: [4-byte big-endian uint32 length][UTF-8 JSON payload].
"""

from __future__ import annotations

import json
import socket
import struct
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

MAX_MESSAGE_SIZE = 50 * 1024 * 1024  # 50 MB


class MessageType(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    STREAM = "stream"


class Status(str, Enum):
    OK = "ok"
    ERROR = "error"


@dataclass
class Message:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType = MessageType.REQUEST
    action: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    status: Status | None = None
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_bytes(self) -> bytes:
        d = asdict(self)
        payload = json.dumps(d).encode("utf-8")
        return struct.pack("!I", len(payload)) + payload

    @classmethod
    def from_dict(cls, d: dict) -> Message:
        return cls(
            id=d.get("id", ""),
            type=MessageType(d["type"]) if "type" in d else MessageType.RESPONSE,
            action=d.get("action", ""),
            params=d.get("params", {}),
            status=Status(d["status"]) if d.get("status") else None,
            data=d.get("data", {}),
            error=d.get("error"),
        )


def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def recv_message(sock: socket.socket) -> Message | None:
    header = _recv_exact(sock, 4)
    if header is None:
        return None
    length = struct.unpack("!I", header)[0]
    if length > MAX_MESSAGE_SIZE:
        raise ValueError(f"Message too large: {length} bytes")
    payload = _recv_exact(sock, length)
    if payload is None:
        return None
    d = json.loads(payload.decode("utf-8"))
    return Message.from_dict(d)


def send_message(sock: socket.socket, msg: Message) -> None:
    sock.sendall(msg.to_bytes())
