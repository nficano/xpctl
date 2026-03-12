"""Helpers for working with bundled package resources."""

from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path
import shutil

INSTALLERS_DIR = Path(__file__).resolve().parent.parent.parent / "installs"

__all__ = [
    "copy_installer_asset",
    "read_remote_script",
    "write_agent_source",
    "write_bootstrap_batch",
]


def write_agent_source(destination: str | Path) -> Path:
    """Write the packaged Windows XP agent to *destination*."""
    target = Path(destination)
    source = files("xpctl.assets").joinpath("agent.py").read_text(encoding="utf-8")
    target.write_text(source, encoding="utf-8", newline="\n")
    return target


def write_bootstrap_batch(destination: str | Path) -> Path:
    """Write the packaged XP bootstrap batch file to *destination*."""
    target = Path(destination)
    source = (
        files("xpctl.assets")
        .joinpath("bootstrap_xpctl.bat")
        .read_text(encoding="utf-8")
    )
    target.write_text(source, encoding="utf-8", newline="\r\n")
    return target


def copy_installer_asset(name: str, destination: str | Path) -> Path:
    """Copy a bundled installer asset to *destination*."""
    target = Path(destination)
    repo_source = INSTALLERS_DIR / name
    if repo_source.is_file():
        shutil.copy2(repo_source, target)
        return target

    source = files("xpctl.assets.installers").joinpath(name).read_bytes()
    target.write_bytes(source)
    return target


def read_remote_script(name: str) -> str:
    """Read a bundled remote Python script by name."""
    return (
        files("xpctl.assets.scripts").joinpath(f"{name}.py").read_text(encoding="utf-8")
    )
