"""Shared CLI helpers for xpctl."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import click
from rich.console import Console

from xpctl.client import XPClient
from xpctl.protocol import JSON_MARKER
from xpctl.transport.ssh_support.translation import quote_cmd_value
from xpctl.transport.tcp import TCPTransport

__all__ = ["JSON_MARKER", "common_options", "console", "err_console"]

console = Console()
err_console = Console(stderr=True)

_common = [
    click.option(
        "--host",
        envvar="XPCTL_HOST",
        required=True,
        help="XP VM hostname or IP address.",
    ),
    click.option("--port", default=9578, type=int, help="Agent TCP port"),
    click.option(
        "--transport",
        "transport_mode",
        type=click.Choice(["auto", "tcp", "ssh"]),
        default="auto",
    ),
    click.option(
        "--password",
        default="",
        envvar="XPCTL_SSH_PASSWORD",
        hide_input=True,
        help="Optional SSH password. Leave unset for key-based auth.",
    ),
    click.option(
        "--user",
        default="",
        envvar="XPCTL_SSH_USER",
        help="Optional SSH user for SSH transport.",
    ),
    click.option(
        "--verify-host-key/--insecure-host-key",
        "verify_host_key",
        default=True,
        show_default=True,
        help="Verify the SSH host key against known_hosts.",
    ),
]


def common_options(fn: Any) -> Any:
    """Decorator that adds the shared ``--host``, ``--port``, etc. CLI options."""
    for opt in reversed(_common):
        fn = opt(fn)
    return fn


def _client(ctx: click.Context) -> XPClient:
    """Build an XPClient from the root context params."""
    p = ctx.ensure_object(dict)
    return XPClient(
        host=p["host"],
        port=p["port"],
        transport=p["transport_mode"],
        password=p["password"],
        user=p["user"],
        verify_host_key=p["verify_host_key"],
    )


def _default_remote_download_dir() -> str:
    """Return the default remote directory for downloads."""
    return r"C:\xpctl\downloads"


def _exe_filename_from_url(url: str) -> str:
    """Extract an ``.exe`` filename from a URL, adding the extension if absent."""
    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name
    if not name:
        return "download.exe"
    if not name.lower().endswith(".exe"):
        return f"{name}.exe"
    return name


def _print_exec_result(
    result: dict[str, Any], ctx: click.Context | None = None
) -> None:
    """Print stdout/stderr from a remote execution result."""
    if result.get("stdout"):
        console.print(result["stdout"], end="", highlight=False)
    if result.get("stderr"):
        err_console.print(result["stderr"], end="", highlight=False)
    if ctx is not None:
        ctx.exit(result.get("returncode", 0))


def _ensure_success(result: dict[str, Any], action: str) -> None:
    """Raise ``ClickException`` if *result* indicates a non-zero return code."""
    if result.get("returncode", 0) != 0:
        raise click.ClickException(
            f"{action} failed (rc={result.get('returncode')}): {result.get('stderr', '').strip()}"
        )


def _exec_python_json(
    client: XPClient,
    script: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 60,
) -> Any:
    """Run *script* on the remote host and parse its JSON output."""
    payload_json = json.dumps(payload or {})
    runner = (
        "import json\n"
        f"payload = json.loads({payload_json!r})\n"
        f"{script}\n"
        f"print('{JSON_MARKER}' + json.dumps(result))\n"
    )
    resp = client.exec_python(runner, timeout=timeout)
    if resp.get("returncode", 1) != 0:
        raise click.ClickException(
            resp.get("stderr", "").strip() or "Remote python failed"
        )

    stdout = resp.get("stdout", "")
    idx = stdout.rfind(JSON_MARKER)
    if idx == -1:
        raise click.ClickException(
            "Failed to parse structured response from remote python"
        )
    payload_text = stdout[idx + len(JSON_MARKER) :].strip()
    return json.loads(payload_text)


_cmd_quote = quote_cmd_value


def _run_host_command(
    cmd: list[str],
    ssh_host: str = "",
    ssh_user: str = "root",
) -> subprocess.CompletedProcess[str]:
    """Run *cmd* locally or over SSH if *ssh_host* is set."""
    if not ssh_host:
        return subprocess.run(cmd, capture_output=True, text=True)

    target = f"{ssh_user}@{ssh_host}" if ssh_user else ssh_host
    remote_cmd = " ".join(shlex.quote(c) for c in cmd)
    full_cmd = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        target,
        remote_cmd,
    ]
    return subprocess.run(full_cmd, capture_output=True, text=True)


def _require_tcp_agent(client: XPClient, feature: str) -> None:
    """Raise ``ClickException`` if *client* is not using the TCP transport."""
    if isinstance(getattr(client, "_transport", None), TCPTransport):
        return
    raise click.ClickException(
        f"{feature} requires the TCP agent transport. Start the agent or pass --transport tcp."
    )
