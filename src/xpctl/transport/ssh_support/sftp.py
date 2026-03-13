"""SFTP-backed file helpers for the SSH transport."""

from __future__ import annotations

import base64
import binascii
import shlex
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from xpctl.transport.ssh_support.translation import PathTranslator

REMOTE_PARENT_TIMEOUT = 15

CommandRunner = Callable[[str, int], object]
SFTPTransfer = Callable[[str, str], None]
SFTPSessionChecker = Callable[[], None]

__all__ = [
    "REMOTE_PARENT_TIMEOUT",
    "SFTPAPI",
    "temporary_binary_file",
    "temporary_text_file",
]


@contextmanager
def temporary_binary_file(
    data: bytes = b"",
    *,
    suffix: str = "",
) -> Iterator[Path]:
    """Create a temporary binary file and remove it after use."""
    with NamedTemporaryFile(mode="wb", delete=False, suffix=suffix) as handle:
        path = Path(handle.name)
        handle.write(data)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


@contextmanager
def temporary_text_file(
    text: str,
    *,
    suffix: str = "",
    newline: str = "",
) -> Iterator[Path]:
    """Create a temporary text file and remove it after use."""
    with NamedTemporaryFile(
        mode="w",
        delete=False,
        suffix=suffix,
        encoding="utf-8",
        newline=newline,
    ) as handle:
        path = Path(handle.name)
        handle.write(text)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


@dataclass(frozen=True)
class SFTPAPI:
    """Handle SFTP file transfer and path preparation."""

    run_bash: CommandRunner
    ensure_sftp: SFTPSessionChecker
    sftp_put: SFTPTransfer
    sftp_get: SFTPTransfer
    translator: PathTranslator

    def ensure_remote_parent(self, remote_path: str) -> None:
        """Create the parent directory for *remote_path* when needed."""
        parent = self.translator.remote_parent(remote_path)
        if not parent:
            return
        command = f"mkdir -p {shlex.quote(self.translator.to_cygwin_path(parent))}"
        self.run_bash(command, REMOTE_PARENT_TIMEOUT)

    def put(self, local_path: str, remote_path: str) -> None:
        """Upload a local file to *remote_path*."""
        self.ensure_sftp()
        self.sftp_put(local_path, self.translator.to_cygwin_path(remote_path))

    def get(self, remote_path: str, local_path: str) -> None:
        """Download *remote_path* to a local file."""
        self.ensure_sftp()
        self.sftp_get(self.translator.to_cygwin_path(remote_path), local_path)

    def upload(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Handle ``file_upload`` requests."""
        path = str(params.get("path", ""))
        mode = str(params.get("mode", "write")).lower()
        if mode != "write":
            raise NotImplementedError("Only mode='write' is supported in SSH mode")

        try:
            raw = base64.b64decode(params.get("data", ""))
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"Invalid base64 upload data: {exc}") from exc
        self.ensure_remote_parent(path)
        with temporary_binary_file(raw) as local_tmp:
            self.put(str(local_tmp), path)
        return {"bytes_written": len(raw), "path": path}

    def download(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Handle ``file_download`` requests."""
        path = str(params.get("path", ""))
        with temporary_binary_file() as local_tmp:
            self.get(path, str(local_tmp))
            raw = local_tmp.read_bytes()
        return {
            "data": base64.b64encode(raw).decode("ascii"),
            "size": len(raw),
            "path": path,
        }
