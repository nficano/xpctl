"""SSH transport backed by Cygwin bash on the XP host."""

from __future__ import annotations

import csv
import shlex
import subprocess
import time
from collections.abc import Callable
from functools import wraps
from pathlib import PureWindowsPath
from typing import Any, Concatenate, ParamSpec, TypeVar, cast

import paramiko

from xpctl.resources import read_remote_script
from xpctl.transport.base import Transport
from xpctl.transport.ssh_support import (
    SFTPAPI,
    BatchAPI,
    InstallAPI,
    PathTranslator,
    PythonAPI,
    ShellAPI,
    quote_cmd_value,
)

__all__ = ["SSHTransport"]

AUTH_TIMEOUT = 8
CONNECT_TIMEOUT = 8
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_BASE = 1
SSH_BUFFER_SIZE = 32768
SSH_POLL_INTERVAL = 0.05
P = ParamSpec("P")
R = TypeVar("R")


def _with_ssh_retry(
    method: Callable[Concatenate[SSHTransport, P], R],
) -> Callable[Concatenate[SSHTransport, P], R]:
    """Retry transient SSH command failures with linear backoff."""

    @wraps(method)
    def wrapper(self: SSHTransport, *args: P.args, **kwargs: P.kwargs) -> R:
        last_error: Exception | None = None
        for attempt in range(RETRY_ATTEMPTS):
            try:
                return method(self, *args, **kwargs)
            except subprocess.TimeoutExpired:
                raise
            except Exception as exc:
                last_error = exc
                if not self._should_retry_exception(exc, attempt):
                    raise
                time.sleep(RETRY_BACKOFF_BASE + attempt)
        raise RuntimeError(f"SSH command execution failed: {last_error}")

    return cast(Callable[..., R], wrapper)


class SSHTransport(Transport):
    """Execute xpctl actions over non-interactive SSH + Cygwin bash."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        user: str = "",
        password: str = "",
        verify_host_key: bool = True,
        python_path: str = r"C:\Python34\python.exe",
        bash_path: str = "bash",
    ):
        self.host = host
        self.user = user
        self.password = password
        self.verify_host_key = verify_host_key
        self.python_path = python_path
        self.bash_path = bash_path
        self._connected = False
        self._client: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None
        self._sftp_error: Exception | None = None
        self._paths = PathTranslator(python_path=PureWindowsPath(python_path))
        self._python = PythonAPI(self._run_bash, self._paths)
        self._shell = ShellAPI(
            self._run_bash,
            self._python.run,
            self._python_version,
            self._paths,
        )
        self._sftp_api = SFTPAPI(
            self._run_bash,
            self._ensure_sftp,
            self._sftp_put,
            self._sftp_get,
            self._paths,
        )
        self._bat = BatchAPI(
            self._run_bash,
            self._sftp_api.ensure_remote_parent,
            self.scp_push,
        )
        self._install = InstallAPI(self._run_python_json, self._paths)
        self._handlers = self._build_handlers()

    def connect(self) -> None:
        """Open an SSH connection and SFTP channel to the remote host."""
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if self.verify_host_key:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_args: dict[str, Any] = {
            "hostname": self.host,
            "timeout": CONNECT_TIMEOUT,
            "banner_timeout": CONNECT_TIMEOUT,
            "auth_timeout": AUTH_TIMEOUT,
            "look_for_keys": not bool(self.password),
            "allow_agent": not bool(self.password),
        }
        if self.user:
            connect_args["username"] = self.user
        if self.password:
            connect_args["password"] = self.password

        try:
            client.connect(**connect_args)
        except Exception as exc:
            raise ConnectionError(f"SSH connection failed: {exc}") from exc

        self._client = client
        self._connected = True
        self._sftp = None
        self._sftp_error = None
        try:
            self._sftp = client.open_sftp()
        except Exception as exc:
            self._sftp_error = exc

    def disconnect(self) -> None:
        """Close the SSH and SFTP connections."""
        if self._sftp is not None:
            self._sftp.close()
            self._sftp = None
        if self._client is not None:
            self._client.close()
            self._client = None
        self._connected = False

    def send_request(
        self, action: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Dispatch *action* to the appropriate SSH handler and return the result."""
        handler = self._handlers.get(action)
        if handler is None:
            raise NotImplementedError(
                f"Action '{action}' not supported over SSH transport"
            )
        return handler(params or {})

    def is_connected(self) -> bool:
        """Return ``True`` if the SSH session is active."""
        return self._connected

    def run_command(
        self,
        command: str,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        """Run a raw SSH command and return the completed process."""
        return self._run_ssh(command, timeout=timeout)

    # -- action handlers ----------------------------------------------------

    def _handle_file_list(self, params: dict[str, Any]) -> dict[str, Any]:
        script = read_remote_script("file_list")
        return self._run_python_json(script, params, timeout=60)

    def _handle_file_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        script = read_remote_script("file_delete")
        return self._run_python_json(script, params, timeout=60)

    def _handle_file_stat(self, params: dict[str, Any]) -> dict[str, Any]:
        script = read_remote_script("file_stat")
        return self._run_python_json(script, params, timeout=30)

    def _handle_sysinfo(self) -> dict[str, Any]:
        result = self._run_bash("cmd.exe /c systeminfo", timeout=60)
        data: dict[str, Any] = {"raw": result.stdout}
        for line in result.stdout.splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            key = k.strip().lower().replace(" ", "_")
            data[key] = v.strip()
        return data

    def _handle_proclist(self, params: dict[str, Any]) -> dict[str, Any]:
        filter_str = str(params.get("filter", "")).lower()
        result = self._run_bash("cmd.exe /c tasklist /fo csv /nh", timeout=30)
        reader = csv.reader(result.stdout.splitlines())
        processes = []
        for row in reader:
            if len(row) < 2:
                continue
            name = row[0].strip()
            if filter_str and filter_str not in name.lower():
                continue
            try:
                pid = int(row[1])
            except ValueError:
                continue
            mem = row[4].strip() if len(row) > 4 else ""
            processes.append({"name": name, "pid": pid, "memory": mem})
        return {"raw": result.stdout, "processes": processes}

    def _handle_services(self, params: dict[str, Any]) -> dict[str, Any]:
        action = str(params.get("action", "list")).lower()
        name = str(params.get("name", ""))

        if action == "list":
            result = self._run_bash("cmd.exe /c net start", timeout=30)
            services = []
            for line in result.stdout.splitlines():
                val = line.strip()
                if not val:
                    continue
                if val.startswith("These Windows services are started:"):
                    continue
                if val.startswith("The command completed successfully."):
                    continue
                services.append(val)
            return {"services": services}

        if action in ("start", "stop"):
            if not name:
                raise ValueError("Service name required")
            inner = f"net {action} {self._cmd_quote(name)}"
            result = self._run_bash(f"cmd.exe /c {shlex.quote(inner)}", timeout=30)
            return self._result_to_exec_response(result, timed_out=False)

        if action == "status":
            if not name:
                raise ValueError("Service name required")
            inner = f"sc query {self._cmd_quote(name)}"
            result = self._run_bash(f"cmd.exe /c {shlex.quote(inner)}", timeout=30)
            return self._result_to_exec_response(result, timed_out=False)

        raise ValueError(f"Unknown service action: {action}")

    # -- SCP helpers --------------------------------------------------------

    def scp_push(self, local_path: str, remote_path: str, timeout: int = 120) -> None:
        """Upload a local file to the remote host via SFTP."""
        self._ensure_sftp()
        assert self._sftp is not None
        channel = self._sftp.get_channel()
        original_timeout = channel.gettimeout() if channel else None
        try:
            if channel:
                channel.settimeout(float(timeout))
            self._sftp_api.put(local_path, remote_path)
        finally:
            if channel:
                channel.settimeout(original_timeout)

    def scp_pull(self, remote_path: str, local_path: str, timeout: int = 120) -> None:
        """Download a file from the remote host to a local path via SFTP."""
        self._ensure_sftp()
        assert self._sftp is not None
        channel = self._sftp.get_channel()
        original_timeout = channel.gettimeout() if channel else None
        try:
            if channel:
                channel.settimeout(float(timeout))
            self._sftp_api.get(remote_path, local_path)
        finally:
            if channel:
                channel.settimeout(original_timeout)

    # -- internal -----------------------------------------------------------

    @_with_ssh_retry
    def _run_ssh(
        self,
        remote_cmd: str,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        if self._client is None:
            raise ConnectionError("Not connected")
        try:
            _stdin, stdout, _stderr = self._client.exec_command(
                remote_cmd,
                timeout=timeout,
            )
            channel = stdout.channel
            channel.settimeout(timeout)
            deadline = time.time() + timeout
            stdout_chunks: list[bytes] = []
            stderr_chunks: list[bytes] = []

            while True:
                while channel.recv_ready():
                    stdout_chunks.append(channel.recv(SSH_BUFFER_SIZE))
                while channel.recv_stderr_ready():
                    stderr_chunks.append(channel.recv_stderr(SSH_BUFFER_SIZE))

                if (
                    channel.exit_status_ready()
                    and not channel.recv_ready()
                    and not channel.recv_stderr_ready()
                ):
                    break

                if time.time() >= deadline:
                    channel.close()
                    raise subprocess.TimeoutExpired(
                        cmd=remote_cmd,
                        timeout=timeout,
                        output=b"".join(stdout_chunks),
                        stderr=b"".join(stderr_chunks),
                    )
                time.sleep(SSH_POLL_INTERVAL)

            returncode = channel.recv_exit_status()
            return subprocess.CompletedProcess(
                args=["ssh", self.host, remote_cmd],
                returncode=returncode,
                stdout=b"".join(stdout_chunks).decode("utf-8", errors="replace"),
                stderr=b"".join(stderr_chunks).decode("utf-8", errors="replace"),
            )
        except TimeoutError as exc:
            raise subprocess.TimeoutExpired(
                cmd=remote_cmd,
                timeout=timeout,
            ) from exc

    def _run_bash(
        self, command: str, timeout: int = 30
    ) -> subprocess.CompletedProcess[str]:
        wrapped = f"{self.bash_path} --noprofile --norc -lc {shlex.quote(command)}"
        return self._run_ssh(wrapped, timeout=timeout)

    def _run_python(
        self, code: str, timeout: int = 30
    ) -> subprocess.CompletedProcess[str]:
        return self._python.run(code, timeout=timeout)

    def _run_python_json(
        self,
        script: str,
        payload: dict[str, Any],
        timeout: int = 30,
    ) -> dict[str, Any]:
        return self._python.run_json(script, payload, timeout=timeout)

    def _to_cygwin_path(self, path: str) -> str:
        return self._paths.to_cygwin_path(path)

    def _cmd_quote(self, value: str) -> str:
        return quote_cmd_value(value)

    def _python_version(self) -> str:
        result = self._run_bash(
            f"{shlex.quote(self._to_cygwin_path(self.python_path))} -V", timeout=10
        )
        return (result.stdout or result.stderr).strip()

    def _timeout_response(self, exc: subprocess.TimeoutExpired) -> dict[str, Any]:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return {
            "stdout": stdout,
            "stderr": stderr,
            "returncode": 124,
            "timed_out": True,
        }

    def _result_to_exec_response(
        self,
        result: subprocess.CompletedProcess[str],
        timed_out: bool,
    ) -> dict[str, Any]:
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "timed_out": timed_out,
        }

    def _ensure_sftp(self) -> None:
        if self._sftp is None:
            detail = f": {self._sftp_error}" if self._sftp_error is not None else ""
            raise ConnectionError(f"SFTP channel is not connected{detail}")

    def _sftp_put(self, local_path: str, remote_path: str) -> None:
        self._ensure_sftp()
        assert self._sftp is not None  # guaranteed by _ensure_sftp
        self._sftp.put(local_path, remote_path)

    def _sftp_get(self, remote_path: str, local_path: str) -> None:
        self._ensure_sftp()
        assert self._sftp is not None  # guaranteed by _ensure_sftp
        self._sftp.get(remote_path, local_path)

    def _should_retry_exception(self, exc: Exception, attempt: int) -> bool:
        if attempt >= RETRY_ATTEMPTS - 1:
            return False
        if isinstance(exc, ConnectionError):
            return False
        transient = (
            "Connection reset",
            "Connection timed out",
            "Connection closed",
            "No route to host",
            "kex_exchange_identification",
        )
        return any(message in str(exc) for message in transient)

    def _build_handlers(self) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
        return {
            "agent_info": lambda _params: self._shell.agent_info(),
            "agent_shutdown": lambda _params: self._shell.agent_shutdown(),
            "bat_create": self._bat.create,
            "bat_run": self._bat.run,
            "exec": self._shell.exec,
            "file_delete": self._handle_file_delete,
            "file_download": self._sftp_api.download,
            "file_list": self._handle_file_list,
            "file_stat": self._handle_file_stat,
            "file_upload": self._sftp_api.upload,
            "install_startup": self._install.install_startup,
            "ping": lambda _params: self._shell.ping(),
            "proclist": self._handle_proclist,
            "reboot": self._shell.reboot,
            "remove_startup": self._install.remove_startup,
            "services": self._handle_services,
            "startup_status": self._install.startup_status,
            "sysinfo": lambda _params: self._handle_sysinfo(),
        }
