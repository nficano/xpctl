"""Startup/install helpers for the SSH transport."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from xpctl.templates import render
from xpctl.transport.ssh_support.translation import PathTranslator
from xpctl.transport.tcp import DEFAULT_PORT

DEFAULT_INSTALL_TIMEOUT = 30
STARTUP_REG_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REG_NAME = "xpctl_agent"

PythonJSONRunner = Callable[[str, dict[str, Any], int], dict[str, Any]]

__all__ = [
    "DEFAULT_INSTALL_TIMEOUT",
    "STARTUP_REG_KEY",
    "STARTUP_REG_NAME",
    "InstallAPI",
]


@dataclass(frozen=True)
class InstallAPI:
    """Manage startup registration through templated Python scripts."""

    run_python_json: PythonJSONRunner
    translator: PathTranslator

    def _run_template(self, template_name: str, **context: Any) -> dict[str, Any]:
        script = render(template_name, **context)
        return self.run_python_json(script, {}, DEFAULT_INSTALL_TIMEOUT)

    def install_startup(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Register the agent to start on boot."""
        port = int(params.get("port", DEFAULT_PORT))
        return self._run_template(
            "install_startup.py.j2",
            reg_key=STARTUP_REG_KEY,
            reg_name=STARTUP_REG_NAME,
            command=self.translator.startup_command(port),
        )

    def remove_startup(self, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Remove the agent startup registration."""
        del params
        return self._run_template(
            "remove_startup.py.j2",
            reg_key=STARTUP_REG_KEY,
            reg_name=STARTUP_REG_NAME,
        )

    def startup_status(self, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return the current agent startup registration status."""
        del params
        return self._run_template(
            "startup_status.py.j2",
            reg_key=STARTUP_REG_KEY,
            reg_name=STARTUP_REG_NAME,
        )
