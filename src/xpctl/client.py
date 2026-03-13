"""High-level client API for xpctl."""

from __future__ import annotations

import base64
import socket as _socket
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from xpctl.transport.base import Transport
from xpctl.transport.factory import (
    ConnectionProfile,
    DefaultTransportFactory,
    TransportFactory,
    TransportMode,
)

__all__ = ["DebuggerProxy", "XPClient"]


class DebuggerProxy:
    """Lazy namespace that provides ``client.debug.olly``, ``client.debug.windbg``, etc."""

    def __init__(self, client: XPClient):
        self._client = client
        self.olly = _DebuggerHandle(client, "olly")
        self.windbg = _DebuggerHandle(client, "cdb")  # uses cdb for piped I/O
        self.x64dbg = _DebuggerHandle(client, "x64dbg")

    def list(self) -> dict[str, str]:
        """Return a mapping of available debugger names to descriptions."""
        return self._client._request("debug_list").get("debuggers", {})

    def ps(self, filter_str: str = "") -> list[dict[str, Any]]:
        """List processes on the remote host, optionally filtered by name."""
        return self._client.processes(filter_str)


class _DebuggerHandle:
    def __init__(self, client: XPClient, name: str):
        self._client = client
        self._name = name

    def launch(self, exe: str, args: list[str] | None = None) -> str:
        """Launch *exe* under the debugger and return the session ID."""
        result = self._client._request(
            "debug_launch",
            {
                "debugger": self._name,
                "exe": exe,
                "args": args or [],
            },
        )
        return result["session_id"]

    def attach(self, pid: int) -> str:
        """Attach the debugger to a running process by *pid*."""
        result = self._client._request(
            "debug_attach",
            {
                "debugger": self._name,
                "pid": pid,
            },
        )
        return result["session_id"]

    def cmd(self, session_id: str, command: str) -> str:
        """Send a debugger command and return its output."""
        result = self._client._request(
            "debug_cmd",
            {
                "session_id": session_id,
                "command": command,
            },
        )
        return result.get("output", "")

    def run_script(self, session_id: str, script_path: str) -> str:
        """Run a debugger script file; uploads local files automatically."""
        # If it's a local file, upload it first
        local = Path(script_path)
        if local.is_file():
            remote_path = "C:\\xpctl\\scripts\\" + local.name
            self._client.upload(str(local), remote_path)
            script_path = remote_path

        result = self._client._request(
            "debug_script",
            {
                "debugger": self._name,
                "session_id": session_id,
                "script_path": script_path,
            },
        )
        return result.get("result", "")

    def log(self, session_id: str) -> str:
        """Retrieve the debugger log output for *session_id*."""
        result = self._client._request(
            "debug_log",
            {
                "session_id": session_id,
            },
        )
        return result.get("output", "")

    def detach(self, session_id: str) -> None:
        """Detach the debugger from *session_id*."""
        self._client._request("debug_detach", {"session_id": session_id})


class XPClient:
    """High-level client for interacting with a Windows XP VM."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9578,
        transport: TransportMode = "auto",
        password: str = "",
        user: str = "",
        verify_host_key: bool = True,
        timeout: float = 10.0,
        transport_factory: TransportFactory | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        socket_factory: Callable[..., _socket.socket] = _socket.socket,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.user = user
        self.verify_host_key = verify_host_key
        self.timeout = timeout
        self._transport_mode: TransportMode = transport
        self._transport_factory = transport_factory or DefaultTransportFactory()
        self._sleep = sleep
        self._monotonic = monotonic
        self._socket_factory = socket_factory
        self._transport: Transport | None = None
        self.debug = DebuggerProxy(self)

    # -- connection ---------------------------------------------------------

    def connect(self) -> None:
        """Establish a connection to the remote agent."""
        if self._transport is not None:
            return
        transport = self._transport_factory.create(
            self._transport_mode,
            self._connection_profile(),
        )
        transport.connect()
        self._transport = transport

    def disconnect(self) -> None:
        """Disconnect from the remote agent."""
        if self._transport:
            self._transport.disconnect()
            self._transport = None

    def __enter__(self) -> XPClient:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.disconnect()

    def _connection_profile(self) -> ConnectionProfile:
        """Build a reusable connection profile for transport factories."""
        return ConnectionProfile(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            timeout=self.timeout,
            verify_host_key=self.verify_host_key,
        )

    @staticmethod
    def _cmd_quote(value: str) -> str:
        """Quote a value for use inside a ``cmd.exe`` command line."""
        return '"' + value.replace('"', '""') + '"'

    def _tcp_ping_once(self, timeout: float) -> bool:
        """Return ``True`` when the TCP agent answers a ping."""
        probe = self._transport_factory.create_tcp(
            ConnectionProfile(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                timeout=timeout,
                probe_timeout=timeout,
                verify_host_key=self.verify_host_key,
            )
        )
        try:
            probe.connect()
            response = probe.send_request("ping")
        finally:
            with suppress(Exception):
                probe.disconnect()
        return response.get("pong", False)

    def _request(
        self, action: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self._transport:
            raise ConnectionError("Not connected — call connect() first")
        return self._transport.send_request(action, params)

    # -- remote execution ---------------------------------------------------

    def exec(self, cmd: str, timeout: int = 30) -> dict[str, Any]:
        """Execute a ``cmd.exe`` command on the remote host."""
        return self._request("exec", {"cmd": cmd, "timeout": timeout, "shell": "cmd"})

    def exec_python(self, code: str, timeout: int = 30) -> dict[str, Any]:
        """Execute Python *code* on the remote host."""
        return self._request(
            "exec", {"cmd": code, "timeout": timeout, "shell": "python"}
        )

    # -- remote interactive python shell ------------------------------------

    def pyshell_eval(self, code: str, session_id: str = "default") -> dict[str, Any]:
        """Evaluate *code* in a persistent remote Python shell session."""
        return self._request("pyshell_eval", {"code": code, "session_id": session_id})

    def pyshell_reset(self, session_id: str = "default") -> dict[str, Any]:
        """Reset (clear) a persistent remote Python shell session."""
        return self._request("pyshell_reset", {"session_id": session_id})

    # -- batch files --------------------------------------------------------

    def bat_run(
        self, path: str, args: list[str] | None = None, timeout: int = 60
    ) -> dict[str, Any]:
        """Run a batch file at *path* on the remote host."""
        return self._request(
            "bat_run", {"path": path, "args": args or [], "timeout": timeout}
        )

    def bat_push_run(
        self,
        local_path: str | Path,
        remote_dir: str = r"C:\xpctl\scripts",
        args: list[str] | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """Upload a local batch file and run it on the remote host."""
        p = Path(local_path)
        remote_path = f"{remote_dir}\\{p.name}"
        self.exec(f"mkdir {self._cmd_quote(remote_dir)}")
        self.upload(str(p), remote_path)
        return self.bat_run(remote_path, args=args, timeout=timeout)

    def bat_create(self, remote_path: str, commands: list[str]) -> dict[str, Any]:
        """Create a batch file on the remote host from a list of commands."""
        return self._request("bat_create", {"path": remote_path, "content": commands})

    # -- file transfer ------------------------------------------------------

    def upload(self, local_path: str | Path, remote_path: str) -> dict[str, Any]:
        """Upload a local file to *remote_path* on the XP host."""
        data = Path(local_path).read_bytes()
        encoded = base64.b64encode(data).decode("ascii")
        return self._request(
            "file_upload",
            {
                "path": remote_path,
                "data": encoded,
                "mode": "write",
            },
        )

    def download(self, remote_path: str, local_path: str | Path) -> dict[str, Any]:
        """Download a remote file to *local_path*."""
        result = self._request("file_download", {"path": remote_path})
        raw = base64.b64decode(result["data"])
        Path(local_path).write_bytes(raw)
        return {"size": len(raw), "path": str(local_path)}

    def ls(
        self, remote_path: str = ".", recursive: bool = False
    ) -> list[dict[str, Any]]:
        """List files at *remote_path*."""
        result = self._request(
            "file_list", {"path": remote_path, "recursive": recursive}
        )
        return result.get("entries", [])

    def rm(self, remote_path: str, recursive: bool = False) -> dict[str, Any]:
        """Delete a file or directory on the remote host."""
        return self._request(
            "file_delete", {"path": remote_path, "recursive": recursive}
        )

    def stat(self, remote_path: str) -> dict[str, Any]:
        """Return file metadata for *remote_path*."""
        return self._request("file_stat", {"path": remote_path})

    # -- system -------------------------------------------------------------

    def sysinfo(self) -> dict[str, Any]:
        """Return system information from the remote host."""
        return self._request("sysinfo")

    def processes(self, filter_str: str = "") -> list[dict[str, Any]]:
        """List running processes, optionally filtered by name substring."""
        result = self._request("proclist", {"filter": filter_str})
        return result.get("processes", [])

    def services(self, action: str = "list", name: str = "") -> dict[str, Any]:
        """Manage Windows services (list, start, stop, status)."""
        return self._request("services", {"action": action, "name": name})

    # -- agent lifecycle ----------------------------------------------------

    def ping(self) -> bool:
        """Return ``True`` if the remote agent is reachable."""
        try:
            result = self._request("ping")
            return result.get("pong", False)
        except Exception:
            return False

    def agent_info(self) -> dict[str, Any]:
        """Return version and capability info from the remote agent."""
        return self._request("agent_info")

    def agent_shutdown(self) -> None:
        """Request the remote agent to shut down gracefully."""
        try:
            self._request("agent_shutdown")
        except (ConnectionError, BrokenPipeError, OSError):
            pass

    # -- install / startup / reboot -----------------------------------------

    def install_startup(self, port: int = 9578) -> dict[str, Any]:
        """Register agent to start on Windows boot via registry Run key."""
        return self._request("install_startup", {"port": port})

    def remove_startup(self) -> dict[str, Any]:
        """Remove agent from Windows startup."""
        return self._request("remove_startup")

    def startup_status(self) -> dict[str, Any]:
        """Check if agent is registered in Windows startup."""
        return self._request("startup_status")

    def reboot(
        self,
        wait: bool = True,
        force: bool = True,
        timeout: float = 180.0,
        poll_interval: float = 5.0,
    ) -> bool:
        """Reboot the XP machine.

        If *wait* is True, blocks until the agent is reachable again.
        Returns True if the agent came back up, False on timeout.
        """
        try:
            self._request("reboot", {"delay": 0, "force": force})
        except (ConnectionError, BrokenPipeError, OSError):
            pass

        if not wait:
            self.disconnect()
            return True

        self.disconnect()

        down_deadline = self._monotonic() + 30
        while self._monotonic() < down_deadline:
            sock: _socket.socket | None = None
            try:
                sock = self._socket_factory(_socket.AF_INET, _socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect((self.host, self.port))
            except OSError:
                break
            else:
                self._sleep(1)
            finally:
                with suppress(Exception):
                    if sock is not None:
                        sock.close()

        up_deadline = self._monotonic() + timeout
        while self._monotonic() < up_deadline:
            try:
                probe_timeout = max(
                    0.1, min(self.timeout, poll_interval or self.timeout, 5.0)
                )
                if self._tcp_ping_once(probe_timeout):
                    self.connect()
                    return True
            except Exception:
                pass
            self._sleep(poll_interval)

        return False

    # -- convenience --------------------------------------------------------

    def push_and_run(
        self,
        local_script: str | Path,
        remote_dir: str = r"C:\xpctl\scripts",
        timeout: int = 60,
    ) -> dict[str, Any]:
        """Upload a local script and execute it on the remote host."""
        p = Path(local_script)
        remote_path = f"{remote_dir}\\{p.name}"
        self.exec(f"mkdir {self._cmd_quote(remote_dir)}")
        self.upload(str(p), remote_path)

        if p.suffix.lower() == ".bat":
            return self.bat_run(remote_path, timeout=timeout)

        return self._request(
            "exec",
            {
                "cmd": remote_path,
                "timeout": timeout,
                "shell": "python_file",
            },
        )
