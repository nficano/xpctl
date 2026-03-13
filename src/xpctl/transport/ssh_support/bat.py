"""Batch file helpers for the SSH transport."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from xpctl.transport.ssh_support.sftp import temporary_text_file
from xpctl.transport.ssh_support.shell import as_exec_response
from xpctl.transport.ssh_support.translation import quote_cmd_value

BAT_HEADER = "@echo off\r\n"
DEFAULT_BAT_TIMEOUT = 60

CommandRunner = Callable[[str, int], subprocess.CompletedProcess[str]]
RemoteParentEnsurer = Callable[[str], None]
FileTransfer = Callable[[str, str], None]

__all__ = ["BAT_HEADER", "DEFAULT_BAT_TIMEOUT", "BatchAPI"]


def _bat_contents(lines: tuple[str, ...]) -> str:
    return BAT_HEADER + "".join(f"{line}\r\n" for line in lines)


@dataclass(frozen=True)
class BatchAPI:
    """Create and execute batch files on the remote host."""

    run_bash: CommandRunner
    ensure_remote_parent: RemoteParentEnsurer
    push: FileTransfer

    @as_exec_response
    def run(self, params: Mapping[str, Any]) -> subprocess.CompletedProcess[str]:
        """Run a remote batch file and return an exec response."""
        path = str(params.get("path", ""))
        args = tuple(str(arg) for arg in params.get("args", ()))
        timeout = int(params.get("timeout", DEFAULT_BAT_TIMEOUT))
        quoted_command = " ".join(quote_cmd_value(t) for t in [path, *args])
        return self.run_bash(f"cmd.exe /c {quoted_command}", timeout)

    def create(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Create a remote batch file from inline commands."""
        path = str(params.get("path", ""))
        content = params.get("content", "")
        lines = (
            tuple(str(line) for line in content)
            if isinstance(content, list)
            else (str(content),)
        )
        self.ensure_remote_parent(path)
        with temporary_text_file(
            _bat_contents(lines), suffix=".bat", newline=""
        ) as tmp:
            self.push(str(tmp), path)
        return {"path": path, "created": True}
