"""Factories for constructing xpctl transport implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Literal

from xpctl.transport.base import Transport
from xpctl.transport.ssh import SSHTransport
from xpctl.transport.tcp import DEFAULT_TIMEOUT, TCPTransport

__all__ = [
    "ConnectionProfile",
    "DefaultTransportFactory",
    "TransportFactory",
    "TransportMode",
]

TransportMode = Literal["auto", "tcp", "ssh"]
AUTO_PROBE_TIMEOUT = 3.0


@dataclass(frozen=True, slots=True)
class ConnectionProfile:
    """Immutable connection settings shared by transport constructors."""

    host: str = "127.0.0.1"
    port: int = 9578
    user: str = ""
    password: str = ""
    timeout: float = DEFAULT_TIMEOUT
    probe_timeout: float = AUTO_PROBE_TIMEOUT
    verify_host_key: bool = True


class TransportFactory(ABC):
    """Abstract factory for xpctl transport implementations."""

    def create(self, mode: TransportMode, profile: ConnectionProfile) -> Transport:
        """Create a transport for *mode* using *profile*."""
        if mode == "tcp":
            return self.create_tcp(profile)
        if mode == "ssh":
            return self.create_ssh(profile)
        return self.create_auto(profile)

    def create_auto(self, profile: ConnectionProfile) -> Transport:
        """Create the best transport by probing the TCP agent first."""
        if self.probe_tcp_agent(profile):
            return self.create_tcp(profile)
        return self.create_ssh(profile)

    def probe_tcp_agent(self, profile: ConnectionProfile) -> bool:
        """Return ``True`` if the TCP agent answers a ping."""
        probe = self.create_tcp(replace(profile, timeout=profile.probe_timeout))
        try:
            probe.connect()
            response = probe.send_request("ping")
        except Exception:
            return False
        finally:
            with suppress(Exception):
                probe.disconnect()
        return response.get("pong", False)

    @abstractmethod
    def create_tcp(self, profile: ConnectionProfile) -> Transport:
        """Create an unconnected TCP transport."""

    @abstractmethod
    def create_ssh(self, profile: ConnectionProfile) -> Transport:
        """Create an unconnected SSH transport."""


class DefaultTransportFactory(TransportFactory):
    """Production transport factory backed by the built-in transport classes."""

    def create_tcp(self, profile: ConnectionProfile) -> Transport:
        """Create an unconnected TCP transport."""
        return TCPTransport(profile.host, profile.port, profile.timeout)

    def create_ssh(self, profile: ConnectionProfile) -> Transport:
        """Create an unconnected SSH transport."""
        return SSHTransport(
            profile.host,
            profile.user,
            profile.password,
            verify_host_key=profile.verify_host_key,
        )
