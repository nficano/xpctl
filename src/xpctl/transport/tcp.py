"""TCP transport — connects directly to the packaged XP agent."""

from __future__ import annotations

import socket
from typing import Any

from xpctl.protocol import (
    Message,
    MessageType,
    Status,
    recv_message,
    send_message,
)
from xpctl.transport.base import Transport

DEFAULT_PORT = 9578
DEFAULT_TIMEOUT = 10.0


class TCPTransport(Transport):
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.host, self.port))

    def disconnect(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def send_request(
        self, action: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self._sock:
            raise ConnectionError("Not connected")
        msg = Message(type=MessageType.REQUEST, action=action, params=params or {})
        send_message(self._sock, msg)
        resp = recv_message(self._sock)
        if resp is None:
            raise ConnectionError("Connection closed by agent")
        if resp.status == Status.ERROR:
            raise RuntimeError(f"Agent error: {resp.error}")
        return resp.data

    def is_connected(self) -> bool:
        return self._sock is not None
