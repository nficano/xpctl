"""Abstract transport interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Transport(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def send_request(
        self, action: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a request and return the response data dict.

        Raises ``RuntimeError`` on agent-side errors.
        """
        ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.disconnect()
