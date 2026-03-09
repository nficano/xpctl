"""SSH transport backed by Cygwin bash on the XP host."""

from __future__ import annotations

import base64
import csv
import json
import os
import shlex
import socket as _socket
import subprocess
import tempfile
import time
from pathlib import PureWindowsPath
from typing import Any

import paramiko

from xpctl.resources import read_remote_script
from xpctl.transport.base import Transport

_JSON_MARKER = "__XPSH_JSON__"


class SSHTransport(Transport):
    """Execute xpctl actions over non-interactive SSH + Cygwin bash."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        user: str = "",
        password: str = "",
        python_path: str = r"C:\Python34\python.exe",
        bash_path: str = "bash",
    ):
        self.host = host
        self.user = user
        self.password = password
        self.python_path = python_path
        self.bash_path = bash_path
        self._connected = False
        self._client: paramiko.SSHClient | None = None
        self._sftp: paramiko.SFTPClient | None = None

    def connect(self) -> None:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_args: dict[str, Any] = {
            "hostname": self.host,
            "timeout": 8,
            "banner_timeout": 8,
            "auth_timeout": 8,
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
        self._sftp = client.open_sftp()
        self._connected = True

    def disconnect(self) -> None:
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
        params = params or {}

        if action == "ping":
            result = self._run_bash("echo pong", timeout=5)
            return {"pong": result.returncode == 0 and "pong" in result.stdout.lower()}

        if action == "exec":
            return self._handle_exec(params)

        if action == "bat_run":
            return self._handle_bat_run(params)

        if action == "bat_create":
            return self._handle_bat_create(params)

        if action == "file_upload":
            return self._handle_file_upload(params)

        if action == "file_download":
            return self._handle_file_download(params)

        if action == "file_list":
            return self._handle_file_list(params)

        if action == "file_delete":
            return self._handle_file_delete(params)

        if action == "file_stat":
            return self._handle_file_stat(params)

        if action == "sysinfo":
            return self._handle_sysinfo()

        if action == "proclist":
            return self._handle_proclist(params)

        if action == "services":
            return self._handle_services(params)

        if action == "agent_info":
            return {
                "version": "ssh-mode",
                "python": self._python_version(),
                "transport": "ssh",
                "shell": "cygwin-bash",
                "debuggers": {},
            }

        if action == "agent_shutdown":
            return {"shutting_down": False, "message": "No TCP agent in SSH mode"}

        if action == "reboot":
            delay = params.get("delay", 0)
            force = params.get("force", True)
            flag = "/f " if force else ""
            cmd = f"shutdown /r {flag}/t {delay}"
            self._run_bash(f"cmd.exe /c {shlex.quote(cmd)}", timeout=10)
            return {"rebooting": True, "command": cmd}

        raise NotImplementedError(f"Action '{action}' not supported over SSH transport")

    def is_connected(self) -> bool:
        return self._connected

    # -- action handlers ----------------------------------------------------

    def _handle_exec(self, params: dict[str, Any]) -> dict[str, Any]:
        shell = params.get("shell", "cmd")
        cmd = params.get("cmd", "")
        timeout = int(params.get("timeout", 30))

        try:
            if shell == "python":
                result = self._run_python(cmd, timeout=timeout)
            elif shell == "python_file":
                py_exe = shlex.quote(self._to_cygwin_path(self.python_path))
                script_path = shlex.quote(self._to_cygwin_path(str(cmd)))
                result = self._run_bash(f"{py_exe} {script_path}", timeout=timeout)
            elif shell == "bash":
                result = self._run_bash(cmd, timeout=timeout)
            else:
                result = self._run_bash(
                    f"cmd.exe /c {shlex.quote(str(cmd))}", timeout=timeout
                )
            return self._result_to_exec_response(result, timed_out=False)
        except subprocess.TimeoutExpired as exc:
            return self._timeout_response(exc)

    def _handle_bat_run(self, params: dict[str, Any]) -> dict[str, Any]:
        path = str(params.get("path", ""))
        args = [str(a) for a in params.get("args", [])]
        timeout = int(params.get("timeout", 60))
        cmdline = subprocess.list2cmdline([path, *args])
        try:
            result = self._run_bash(
                f"cmd.exe /c {shlex.quote(cmdline)}", timeout=timeout
            )
            return self._result_to_exec_response(result, timed_out=False)
        except subprocess.TimeoutExpired as exc:
            return self._timeout_response(exc)

    def _handle_bat_create(self, params: dict[str, Any]) -> dict[str, Any]:
        path = str(params.get("path", ""))
        content = params.get("content", "")
        lines = list(content) if isinstance(content, list) else [str(content)]

        self._ensure_remote_parent(path)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".bat", delete=False, newline=""
        ) as fh:
            local_tmp = fh.name
            fh.write("@echo off\r\n")
            for line in lines:
                fh.write(f"{line}\r\n")

        try:
            self.scp_push(local_tmp, path)
        finally:
            try:
                os.unlink(local_tmp)
            except OSError:
                pass
        return {"path": path, "created": True}

    def _handle_file_upload(self, params: dict[str, Any]) -> dict[str, Any]:
        path = str(params.get("path", ""))
        mode = str(params.get("mode", "write")).lower()
        if mode != "write":
            raise NotImplementedError("Only mode='write' is supported in SSH mode")

        raw = base64.b64decode(params.get("data", ""))
        self._ensure_remote_parent(path)
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            local_tmp = fh.name
            fh.write(raw)
        try:
            self.scp_push(local_tmp, path)
        finally:
            try:
                os.unlink(local_tmp)
            except OSError:
                pass
        return {"bytes_written": len(raw), "path": path}

    def _handle_file_download(self, params: dict[str, Any]) -> dict[str, Any]:
        path = str(params.get("path", ""))
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            local_tmp = fh.name
        try:
            self.scp_pull(path, local_tmp)
            raw = open(local_tmp, "rb").read()
        finally:
            try:
                os.unlink(local_tmp)
            except OSError:
                pass

        return {
            "data": base64.b64encode(raw).decode("ascii"),
            "size": len(raw),
            "path": path,
        }

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
        del timeout
        self._ensure_sftp()
        self._sftp_put(local_path, remote_path)

    def scp_pull(self, remote_path: str, local_path: str, timeout: int = 120) -> None:
        del timeout
        self._ensure_sftp()
        self._sftp_get(remote_path, local_path)

    # -- internal -----------------------------------------------------------

    def _run_ssh(
        self,
        remote_cmd: str,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        if self._client is None:
            raise ConnectionError("Not connected")

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                stdin, stdout, stderr = self._client.exec_command(
                    remote_cmd,
                    timeout=timeout,
                )
                del stdin
                channel = stdout.channel
                channel.settimeout(timeout)
                returncode = channel.recv_exit_status()
                return subprocess.CompletedProcess(
                    args=["ssh", self.host, remote_cmd],
                    returncode=returncode,
                    stdout=stdout.read().decode("utf-8", errors="replace"),
                    stderr=stderr.read().decode("utf-8", errors="replace"),
                )
            except _socket.timeout as exc:
                raise subprocess.TimeoutExpired(
                    cmd=remote_cmd,
                    timeout=timeout,
                ) from exc
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1 + attempt)
                    continue
        raise RuntimeError(f"SSH command execution failed: {last_error}")

    def _run_bash(
        self, command: str, timeout: int = 30
    ) -> subprocess.CompletedProcess[str]:
        wrapped = f"{self.bash_path} --noprofile --norc -lc {shlex.quote(command)}"
        return self._run_ssh(wrapped, timeout=timeout)

    def _run_python(
        self, code: str, timeout: int = 30
    ) -> subprocess.CompletedProcess[str]:
        encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
        py_cmd = read_remote_script("run_python_wrapper").replace(
            "__CODE_B64__", encoded
        )
        py_exe = shlex.quote(self._to_cygwin_path(self.python_path))
        return self._run_bash(f"{py_exe} -c {shlex.quote(py_cmd)}", timeout=timeout)

    def _run_python_json(
        self,
        script: str,
        payload: dict[str, Any],
        timeout: int = 30,
    ) -> dict[str, Any]:
        payload_b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode(
            "ascii"
        )
        script_b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
        runner = (
            read_remote_script("run_python_json")
            .replace("__PAYLOAD_B64__", payload_b64)
            .replace("__SCRIPT_B64__", script_b64)
            .replace("__JSON_MARKER__", _JSON_MARKER)
        )

        result = self._run_python(runner, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or "Remote python execution failed"
            )

        idx = result.stdout.rfind(_JSON_MARKER)
        if idx == -1:
            raise RuntimeError("Failed to parse JSON payload from remote command")

        payload_text = result.stdout[idx + len(_JSON_MARKER) :].strip()
        return json.loads(payload_text)

    def _ensure_remote_parent(self, remote_path: str) -> None:
        parent = self._remote_parent(remote_path)
        if not parent:
            return
        self._run_bash(
            f"mkdir -p {shlex.quote(self._to_cygwin_path(parent))}", timeout=15
        )

    def _remote_parent(self, remote_path: str) -> str:
        if self._looks_like_windows_path(remote_path):
            parent = str(PureWindowsPath(remote_path).parent)
            return "" if parent == "." else parent
        parent = os.path.dirname(remote_path)
        return "" if parent == "." else parent

    def _to_cygwin_path(self, path: str) -> str:
        if self._looks_like_windows_path(path):
            normalized = path.replace("\\", "/")
            drive = normalized[0].lower()
            rest = normalized[2:].lstrip("/")
            while "//" in rest:
                rest = rest.replace("//", "/")
            if rest:
                return f"/cygdrive/{drive}/{rest}"
            return f"/cygdrive/{drive}"
        normalized = path.replace("\\", "/")
        while "//" in normalized:
            normalized = normalized.replace("//", "/")
        return normalized

    def _looks_like_windows_path(self, path: str) -> bool:
        return len(path) >= 2 and path[1] == ":" and path[0].isalpha()

    def _cmd_quote(self, value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

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
            raise ConnectionError("SFTP channel is not connected")

    def _sftp_put(self, local_path: str, remote_path: str) -> None:
        target = self._to_cygwin_path(remote_path)
        self._sftp.put(local_path, target)

    def _sftp_get(self, remote_path: str, local_path: str) -> None:
        source = self._to_cygwin_path(remote_path)
        self._sftp.get(source, local_path)

    def _should_retry(self, returncode: int, stderr: str, attempt: int) -> bool:
        if attempt >= 2:
            return False
        if returncode in (5, 255):
            return True
        transient = (
            "Connection reset",
            "Connection timed out",
            "Connection closed",
            "No route to host",
            "kex_exchange_identification",
        )
        return any(s in stderr for s in transient)
