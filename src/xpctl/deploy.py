"""Deploy and manage the packaged agent on a Windows XP host."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from functools import wraps
from pathlib import Path
from typing import Any, Concatenate, ParamSpec, Protocol, TypeVar, cast

from xpctl.resources import write_agent_source
from xpctl.transport.ssh import SSHTransport
from xpctl.transport.tcp import DEFAULT_PORT, TCPTransport

__all__ = ["PYTHON_EXE", "REMOTE_AGENT_DIR", "REMOTE_AGENT_PATH", "AgentDeployer"]

REMOTE_AGENT_DIR = r"C:\xpctl"
REMOTE_AGENT_PATH = rf"{REMOTE_AGENT_DIR}\agent.py"
PYTHON_EXE = r"C:\Python34\python.exe"
SMB_MOUNT = Path("/mnt/xpctl-share")
XP_EXPORT_DIR = "C:/xpctl/share"
AGENT_CONNECT_TIMEOUT = 5.0
STATUS_TIMEOUT = 3.0
WAIT_FOR_AGENT_TIMEOUT = 2.0
WAIT_FOR_AGENT_INTERVAL = 0.5
START_DELAY_SECONDS = 2
STOP_DELAY_SECONDS = 1
REDEPLOY_DELAY_SECONDS = 1
SSH_START_TIMEOUT = 15
SSH_KILL_TIMEOUT = 15
SSH_QUERY_TIMEOUT = 30

P = ParamSpec("P")
R = TypeVar("R")


def _copy_packaged_agent(destination: Path) -> Path:
    """Write the bundled agent source to *destination* and return its path."""
    return write_agent_source(destination)


def _render_template(name: str, /, **context: object) -> str:
    """Render a bundled Jinja template."""
    from xpctl.templates import render

    return render(name, **context)


def _wmic_agent_where_clause(port: int, batch: bool = False) -> str:
    """Build a WMIC WHERE clause to match the agent process on *port*."""
    wildcard = "%%" if batch else "%"
    agent_paths = (
        REMOTE_AGENT_PATH,
        REMOTE_AGENT_PATH.replace("\\", "/"),
    )
    path_clause = " or ".join(
        f"CommandLine like '{wildcard}{path}{wildcard}'" for path in agent_paths
    )
    clauses = [
        "name='python.exe'",
        f"({path_clause})",
        f"CommandLine like '{wildcard}--port {port}{wildcard}'",
    ]
    return " and ".join(clauses)


def _requires_ssh_connection(
    method: Callable[Concatenate[AgentDeployer, P], R],
) -> Callable[Concatenate[AgentDeployer, P], R]:
    """Connect the deployer's SSH transport before invoking *method*."""

    @wraps(method)
    def wrapper(self: AgentDeployer, *args: P.args, **kwargs: P.kwargs) -> R:
        self._ensure_ssh()
        return method(self, *args, **kwargs)

    return cast(Callable[..., R], wrapper)


class AgentDeployer:
    """Handle deployment and lifecycle management for the Windows XP agent."""

    class SSHCommandTransport(Protocol):
        """Protocol for the SSH capabilities required by the deployer."""

        host: str

        def connect(self) -> None:
            """Establish the SSH connection."""
            ...

        def is_connected(self) -> bool:
            """Return whether the transport is connected."""
            ...

        def run_command(
            self,
            command: str,
            timeout: int = SSH_QUERY_TIMEOUT,
        ) -> subprocess.CompletedProcess[str]:
            """Execute *command* remotely."""
            ...

    class TemplateRenderer(Protocol):
        """Callable protocol for template rendering."""

        def __call__(self, name: str, /, **context: object) -> str:
            """Render *name* with *context*."""
            ...

    def __init__(
        self,
        ssh: SSHCommandTransport | None = None,
        smb_mount: Path = SMB_MOUNT,
        tcp_transport_factory: Callable[[str, int, float], TCPTransport] | None = None,
        agent_writer: Callable[[Path], Path] = _copy_packaged_agent,
        render_template: TemplateRenderer = _render_template,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ssh = ssh or SSHTransport()
        self.smb_mount = smb_mount
        self._tcp_transport_factory = tcp_transport_factory or TCPTransport
        self._agent_writer = agent_writer
        self._render_template = render_template
        self._sleep = sleep
        self._monotonic = monotonic

    def deploy(self) -> None:
        r"""Copy the agent over SMB, then install it into ``C:\xpctl`` via SSH."""
        if not self.smb_mount.is_dir():
            raise FileNotFoundError(
                f"SMB share not mounted at {self.smb_mount}. "
                "Configure and mount the XP share before deploying the agent."
            )

        self._agent_writer(self.smb_mount / "agent.py")
        bootstrap = self._write_bootstrap_script()
        result = self._ssh_command(
            f"C:/Python34/python.exe {XP_EXPORT_DIR}/{bootstrap.name}",
        )
        if "Installed agent" not in result.stdout:
            raise RuntimeError(
                f"SSH bootstrap failed (rc={result.returncode}): {result.stderr}\n"
                f"Agent is on the SMB share. Run {bootstrap.name} manually on XP."
            )

    def deploy_smb_only(self, port: int = DEFAULT_PORT) -> None:
        """Copy the agent and helper batch files to the SMB share only."""
        if not self.smb_mount.is_dir():
            raise FileNotFoundError(f"SMB share not mounted at {self.smb_mount}")

        self._agent_writer(self.smb_mount / "agent.py")

        start_bat = self.smb_mount / "start_agent.bat"
        start_bat.write_text(
            self._render_template(
                "start_agent.bat.j2",
                export_dir=r"C:\xpctl\share",
                port=port,
            ).replace("\n", "\r\n"),
            encoding="utf-8",
        )

        stop_bat = self.smb_mount / "stop_agent.bat"
        stop_bat.write_text(
            self._render_template(
                "stop_agent.bat.j2",
                where_clause=_wmic_agent_where_clause(port, batch=True),
            ).replace("\n", "\r\n"),
            encoding="utf-8",
        )

    def start(self, port: int = DEFAULT_PORT) -> None:
        """Start the agent on the remote host via SSH."""
        agent = REMOTE_AGENT_PATH.replace("\\", "/")
        python = PYTHON_EXE.replace("\\", "/")
        log = (REMOTE_AGENT_DIR + "\\agent.log").replace("\\", "/")
        command = f"nohup {python} {agent} --port {port} > {log} 2>&1 & echo started"
        result = self._ssh_command(command, timeout=SSH_START_TIMEOUT)
        if result.returncode == 5:
            raise ConnectionError(
                "SSH rate-limited. Run start_agent.bat on XP manually, or wait and retry."
            )
        if "started" not in result.stdout:
            raise RuntimeError(f"Agent start failed: {result.stdout} {result.stderr}")
        self._sleep(START_DELAY_SECONDS)
        self._wait_for_agent(port)

    def stop(self, port: int = DEFAULT_PORT) -> None:
        """Stop the agent, preferring a graceful TCP shutdown first."""
        last_error: Exception | None = None
        try:
            with self._tcp_client(port, timeout=AGENT_CONNECT_TIMEOUT) as tcp:
                tcp.send_request("agent_shutdown")
            self._sleep(STOP_DELAY_SECONDS)
            return
        except Exception as exc:
            last_error = exc

        if self._kill_agent_via_ssh(port):
            return
        detail = f" (last TCP error: {last_error})" if last_error else ""
        raise RuntimeError(
            f"Unable to stop xpctl agent on port {port} without killing unrelated Python processes{detail}."
        )

    def status(self, port: int = DEFAULT_PORT) -> dict[str, Any]:
        """Check whether the agent is running and return its info."""
        try:
            with self._tcp_client(port, timeout=STATUS_TIMEOUT) as tcp:
                return {"running": True, **tcp.send_request("agent_info")}
        except Exception:
            return {"running": False}

    def redeploy(self, port: int = DEFAULT_PORT) -> None:
        """Stop the agent, redeploy, and start it again."""
        self.stop(port)
        self._sleep(REDEPLOY_DELAY_SECONDS)
        self.deploy()
        self.start(port)

    def install(self, port: int = DEFAULT_PORT) -> None:
        """Deploy, start, and register the agent to boot automatically."""
        self.deploy()
        self.start(port)
        with self._tcp_client(port, timeout=AGENT_CONNECT_TIMEOUT) as tcp:
            tcp.send_request("install_startup", {"port": port})

    def uninstall(self, port: int = DEFAULT_PORT) -> None:
        """Remove startup registration, stop the agent, and delete its files."""
        with suppress(Exception):
            with self._tcp_client(port, timeout=AGENT_CONNECT_TIMEOUT) as tcp:
                tcp.send_request("remove_startup")

        self.stop(port)
        self._ssh_command("cmd.exe /c rmdir /s /q C:\\xpctl")

    def _ensure_ssh(self) -> None:
        """Connect the SSH transport if it is not already connected."""
        if not self.ssh.is_connected():
            self.ssh.connect()

    def _write_bootstrap_script(self) -> Path:
        bootstrap = self.smb_mount / "bootstrap_agent.py"
        export_source = XP_EXPORT_DIR.replace("/", "\\") + "\\agent.py"
        bootstrap.write_text(
            self._render_template(
                "bootstrap_agent.py.j2",
                export_source=export_source,
                remote_agent_dir=REMOTE_AGENT_DIR,
                remote_agent_path=REMOTE_AGENT_PATH,
            ),
            encoding="utf-8",
        )
        return bootstrap

    def _wait_for_agent(self, port: int, timeout: float = 10.0) -> None:
        """Block until the agent responds to a ping or *timeout* elapses."""
        deadline = self._monotonic() + timeout
        while self._monotonic() < deadline:
            try:
                with self._tcp_client(port, timeout=WAIT_FOR_AGENT_TIMEOUT) as tcp:
                    tcp.send_request("ping")
                return
            except Exception:
                self._sleep(WAIT_FOR_AGENT_INTERVAL)
        raise TimeoutError(f"Agent did not start within {timeout}s")

    @_requires_ssh_connection
    def _kill_agent_via_ssh(self, port: int) -> bool:
        """Kill the agent process via WMIC over SSH; return ``True`` if any were killed."""
        query = f'wmic process where "{_wmic_agent_where_clause(port)}" get ProcessId /value'
        result = self._ssh_command(f"cmd.exe /c {query}", timeout=SSH_QUERY_TIMEOUT)
        pids = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line.startswith("ProcessId="):
                continue
            try:
                pids.append(int(line.split("=", 1)[1]))
            except ValueError:
                continue

        for pid in pids:
            self._ssh_command(f"taskkill /f /pid {pid}", timeout=SSH_KILL_TIMEOUT)

        if pids:
            self._sleep(STOP_DELAY_SECONDS)
        return bool(pids)

    @contextmanager
    def _tcp_client(
        self,
        port: int,
        *,
        timeout: float,
    ) -> Iterator[TCPTransport]:
        """Yield a connected TCP transport and always disconnect it."""
        tcp = self._tcp_transport_factory(self.ssh.host, port, timeout)
        tcp.connect()
        try:
            yield tcp
        finally:
            with suppress(Exception):
                tcp.disconnect()

    @_requires_ssh_connection
    def _ssh_command(self, command: str, timeout: int = SSH_QUERY_TIMEOUT) -> Any:
        """Run *command* over SSH after ensuring the transport is connected."""
        return self.ssh.run_command(command, timeout=timeout)
