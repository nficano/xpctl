"""Abstract transport interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

__all__ = ["Transport"]


class Transport(ABC):
    """Abstract base class for xpctl transport implementations."""

    @abstractmethod
    def connect(self) -> None:
        """Establish the connection to the remote host."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Tear down the connection and release resources."""
        ...

    @abstractmethod
    def send_request(
        self, action: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a request and return the response data dict.

        Raises:
            RuntimeError: On agent-side errors.
        """
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Return ``True`` if the transport is currently connected."""
        ...

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.disconnect()
