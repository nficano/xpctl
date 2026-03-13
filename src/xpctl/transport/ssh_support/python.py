"""Python execution helpers for the SSH transport."""

from __future__ import annotations

import base64
import json
import shlex
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from xpctl.protocol import JSON_MARKER
from xpctl.resources import read_remote_script
from xpctl.transport.ssh_support.translation import PathTranslator

DEFAULT_PYTHON_TIMEOUT = 30

CommandRunner = Callable[[str, int], subprocess.CompletedProcess[str]]
ScriptReader = Callable[[str], str]

__all__ = ["DEFAULT_PYTHON_TIMEOUT", "JSON_MARKER", "PythonAPI"]


def _encoded_text(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


@dataclass(frozen=True)
class PythonAPI:
    """Run inline and packaged Python on the remote host."""

    run_bash: CommandRunner
    translator: PathTranslator
    script_reader: ScriptReader = read_remote_script

    def run(
        self,
        code: str,
        timeout: int = DEFAULT_PYTHON_TIMEOUT,
    ) -> subprocess.CompletedProcess[str]:
        """Execute Python *code* on the remote host."""
        runner = self.script_reader("run_python_wrapper").replace(
            "__CODE_B64__", _encoded_text(code)
        )
        python_exe = shlex.quote(
            self.translator.to_cygwin_path(str(self.translator.python_path))
        )
        return self.run_bash(f"{python_exe} -c {shlex.quote(runner)}", timeout)

    def run_json(
        self,
        script: str,
        payload: Mapping[str, Any],
        timeout: int = DEFAULT_PYTHON_TIMEOUT,
    ) -> dict[str, Any]:
        """Run *script* remotely and decode its structured JSON response."""
        runner = (
            self.script_reader("run_python_json")
            .replace("__PAYLOAD_B64__", _encoded_text(json.dumps(dict(payload))))
            .replace("__SCRIPT_B64__", _encoded_text(script))
            .replace("__JSON_MARKER__", JSON_MARKER)
        )
        result = self.run(runner, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(
                result.stderr.strip() or "Remote python execution failed"
            )

        marker_index = result.stdout.rfind(JSON_MARKER)
        if marker_index == -1:
            raise RuntimeError("Failed to parse JSON payload from remote command")
        payload_text = result.stdout[marker_index + len(JSON_MARKER) :].strip()
        return json.loads(payload_text)
