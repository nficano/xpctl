"""Shell execution helpers for the SSH transport."""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import wraps
from typing import Any

from xpctl.transport.ssh_support.translation import PathTranslator

DEFAULT_EXEC_TIMEOUT = 30
EXEC_TIMEOUT_RETURN_CODE = 124
PING_TIMEOUT = 5
REBOOT_TIMEOUT = 10
SHELL_BASH = "bash"
SHELL_CMD = "cmd"
SHELL_PYTHON = "python"
SHELL_PYTHON_FILE = "python_file"

CommandRunner = Callable[[str, int], subprocess.CompletedProcess[str]]
PythonRunner = Callable[[str, int], subprocess.CompletedProcess[str]]
PythonVersionReader = Callable[[], str]

__all__ = [
    "DEFAULT_EXEC_TIMEOUT",
    "EXEC_TIMEOUT_RETURN_CODE",
    "PING_TIMEOUT",
    "REBOOT_TIMEOUT",
    "ShellAPI",
]


def timeout_response(exc: subprocess.TimeoutExpired) -> dict[str, Any]:
    """Translate ``TimeoutExpired`` into the xpctl exec response shape."""
    stdout = exc.stdout or ""
    stderr = exc.stderr or ""
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    return {
        "stdout": stdout,
        "stderr": stderr,
        "returncode": EXEC_TIMEOUT_RETURN_CODE,
        "timed_out": True,
    }


def result_to_exec_response(
    result: subprocess.CompletedProcess[str],
    *,
    timed_out: bool = False,
) -> dict[str, Any]:
    """Translate a ``CompletedProcess`` into the xpctl exec response shape."""
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "timed_out": timed_out,
    }


def as_exec_response(
    fn: Callable[..., subprocess.CompletedProcess[str]],
) -> Callable[..., dict[str, Any]]:
    """Convert ``CompletedProcess`` results into exec responses."""

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return result_to_exec_response(fn(*args, **kwargs))
        except subprocess.TimeoutExpired as exc:
            return timeout_response(exc)

    return wrapper


def _cmd_runner(
    run_bash: CommandRunner,
    command: str,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return run_bash(f"cmd.exe /c {shlex.quote(command)}", timeout)


def _bash_runner(
    run_bash: CommandRunner,
    command: str,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return run_bash(command, timeout)


def _python_file_runner(
    run_bash: CommandRunner,
    translator: PathTranslator,
    command: str,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    python_exe = shlex.quote(translator.to_cygwin_path(str(translator.python_path)))
    script_path = shlex.quote(translator.to_cygwin_path(command))
    return run_bash(f"{python_exe} {script_path}", timeout)


@dataclass(frozen=True)
class ShellAPI:
    """Dispatch shell-style actions over SSH."""

    run_bash: CommandRunner
    run_python: PythonRunner
    python_version: PythonVersionReader
    translator: PathTranslator

    def ping(self) -> dict[str, Any]:
        """Return the SSH-mode ping response."""
        result = self.run_bash("echo pong", PING_TIMEOUT)
        return {"pong": result.returncode == 0 and "pong" in result.stdout.lower()}

    @as_exec_response
    def exec(self, params: Mapping[str, Any]) -> subprocess.CompletedProcess[str]:
        """Execute a shell command and return a standard exec response."""
        timeout = int(params.get("timeout", DEFAULT_EXEC_TIMEOUT))
        command = str(params.get("cmd", ""))
        shell = str(params.get("shell", SHELL_CMD))
        runners: dict[str, Callable[[str, int], subprocess.CompletedProcess[str]]] = {
            SHELL_CMD: lambda value, limit: _cmd_runner(self.run_bash, value, limit),
            SHELL_BASH: lambda value, limit: _bash_runner(self.run_bash, value, limit),
            SHELL_PYTHON: self.run_python,
            SHELL_PYTHON_FILE: lambda value, limit: _python_file_runner(
                self.run_bash,
                self.translator,
                value,
                limit,
            ),
        }
        runner = runners.get(shell, runners[SHELL_CMD])
        return runner(command, timeout)

    def agent_info(self) -> dict[str, Any]:
        """Return the synthetic agent info available in SSH mode."""
        return {
            "version": "ssh-mode",
            "python": self.python_version(),
            "transport": "ssh",
            "shell": "cygwin-bash",
            "debuggers": {},
        }

    def agent_shutdown(self) -> dict[str, Any]:
        """Return the no-op shutdown response for SSH mode."""
        return {"shutting_down": False, "message": "No TCP agent in SSH mode"}

    def reboot(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Request a machine reboot through ``shutdown.exe``."""
        delay = int(params.get("delay", 0))
        force = bool(params.get("force", True))
        force_flag = "/f " if force else ""
        command = f"shutdown /r {force_flag}/t {delay}"
        self.run_bash(f"cmd.exe /c {shlex.quote(command)}", REBOOT_TIMEOUT)
        return {"rebooting": True, "command": command}
