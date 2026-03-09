"""Helpers for working with bundled package resources."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def write_agent_source(destination: str | Path) -> Path:
    """Write the packaged Windows XP agent to *destination*."""
    target = Path(destination)
    source = files("xpctl.assets").joinpath("agent.py").read_text(encoding="utf-8")
    target.write_text(source, encoding="utf-8", newline="\n")
    return target
