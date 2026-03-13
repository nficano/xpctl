"""Path and quoting helpers shared by the SSH transport."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath

from xpctl.transport.tcp import DEFAULT_PORT

DEFAULT_INSTALL_DIR = PureWindowsPath(r"C:\xpctl")

__all__ = ["DEFAULT_INSTALL_DIR", "PathTranslator", "quote_cmd_value"]


def quote_cmd_value(value: str) -> str:
    """Quote *value* for use inside a ``cmd.exe`` command."""
    return '"' + value.replace('"', '""') + '"'


def _windows_drive_prefix(path: PureWindowsPath) -> str:
    return f"/cygdrive/{path.drive[:1].lower()}"


def _posix_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("//"):
        remainder = normalized[2:]
        while "//" in remainder:
            remainder = remainder.replace("//", "/")
        return f"//{remainder}"
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized


@dataclass(frozen=True)
class PathTranslator:
    """Translate remote Windows paths for Cygwin and ``cmd.exe`` usage."""

    python_path: PureWindowsPath = field(
        default_factory=lambda: PureWindowsPath(r"C:\Python34\python.exe")
    )
    install_dir: PureWindowsPath = DEFAULT_INSTALL_DIR

    def __post_init__(self) -> None:
        object.__setattr__(self, "python_path", PureWindowsPath(self.python_path))
        object.__setattr__(self, "install_dir", PureWindowsPath(self.install_dir))

    def looks_like_windows_path(self, path: str) -> bool:
        """Return ``True`` when *path* has a Windows drive prefix."""
        return len(path) >= 2 and path[1] == ":" and path[0].isalpha()

    def remote_parent(self, remote_path: str) -> str:
        """Return the parent directory for a remote path, or ``""``."""
        if self.looks_like_windows_path(remote_path):
            parent = str(PureWindowsPath(remote_path).parent)
            return "" if parent == "." else parent
        parent = str(PurePosixPath(_posix_path(remote_path)).parent)
        return "" if parent == "." else parent

    def to_cygwin_path(self, path: str) -> str:
        """Convert a Windows path into its Cygwin equivalent."""
        if not self.looks_like_windows_path(path):
            return _posix_path(path)

        windows_path = PureWindowsPath(path)
        prefix = _windows_drive_prefix(windows_path)
        parts = tuple(part for part in windows_path.parts[1:] if part not in {"", "."})
        suffix = "/".join(parts)
        return prefix if not suffix else f"{prefix}/{suffix}"

    def startup_command(self, port: int = DEFAULT_PORT) -> str:
        """Build the agent startup command line for the Windows Run key."""
        agent_path = self.install_dir / "agent.py"
        return (
            f"{quote_cmd_value(str(self.python_path))} "
            f"{quote_cmd_value(str(agent_path))} --port {port}"
        )
