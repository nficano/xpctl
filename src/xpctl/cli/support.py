"""Shared CLI helpers for xpctl."""

from __future__ import annotations

import inspect
import json
import shlex
import subprocess
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import click
from rich.console import Console

from xpctl.client import XPClient
from xpctl.config import DEFAULT_PROFILE, load_profile
from xpctl.protocol import JSON_MARKER
from xpctl.transport.ssh_support.translation import quote_cmd_value
from xpctl.transport.tcp import TCPTransport

__all__ = ["JSON_MARKER", "common_options", "console", "err_console"]

console = Console()
err_console = Console(stderr=True)
TRANSPORT_CHOICES = ("auto", "tcp", "ssh")
RUNTIME_DEFAULT_PORT = 9578
CONFIGURE_DEFAULT_PORT = "22"
CONFIGURE_DEFAULT_TRANSPORT = "auto"

_common = [
    click.option(
        "--profile",
        default=DEFAULT_PROFILE,
        show_default=True,
        help="Connection profile from ~/.xpcli/config.",
    ),
    click.option(
        "--host",
        envvar="XPCTL_HOST",
        default=None,
        help="XP VM hostname or IP address.",
    ),
    click.option(
        "--port",
        envvar="XPCTL_PORT",
        default=None,
        type=int,
        help="Port for the selected transport.",
    ),
    click.option(
        "--transport",
        "transport_mode",
        envvar="XPCTL_TRANSPORT",
        type=click.Choice(TRANSPORT_CHOICES),
        default=None,
    ),
    click.option(
        "--password",
        default=None,
        envvar="XPCTL_SSH_PASSWORD",
        hide_input=True,
        help="Optional SSH password. Leave unset for key-based auth.",
    ),
    click.option(
        "--user",
        default=None,
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


def _resolve_connection_settings(
    profile_name: str,
    host: str | None,
    port: int | None,
    transport_mode: str | None,
    user: str | None,
    password: str | None,
    use_profile_defaults: bool = True,
) -> dict[str, str | int | bool]:
    saved = load_profile(profile_name) if use_profile_defaults else {}

    resolved_host = host if host is not None else (saved.get("hostname") or "")
    saved_port = saved.get("port", "")
    resolved_port = (
    saved_port = saved.get("port", "")
    if port is not None:
        resolved_port = port
    else:
        try:
            resolved_port = int(saved_port or RUNTIME_DEFAULT_PORT)
        except ValueError as exc:
            raise click.ClickException(
                f"Invalid port value '{saved_port}' in profile '{profile_name}'."
            ) from exc
    resolved_transport = (
        transport_mode
        if transport_mode is not None
        else (saved.get("transport") or CONFIGURE_DEFAULT_TRANSPORT)
    )
    resolved_user = user if user is not None else saved.get("username", "")
    resolved_password = password if password is not None else saved.get("password", "")

    return {
        "profile": profile_name,
        "host": resolved_host,
        "port": resolved_port,
        "transport_mode": resolved_transport,
        "user": resolved_user,
        "password": resolved_password,
    }


def _client_class() -> type[XPClient]:
    cli_module = import_module("xpctl.cli")
    return getattr(cli_module, "XPClient", XPClient)


def _client(ctx: click.Context) -> XPClient:
    """Build an XPClient from the root context params."""
    p = ctx.ensure_object(dict)
    client_cls = _client_class()
    kwargs: dict[str, Any] = {
        "host": p["host"],
        "port": p["port"],
        "transport": p["transport_mode"],
        "password": p["password"],
        "user": p["user"],
    }
    params = inspect.signature(client_cls).parameters.values()
    if any(param.kind is inspect.Parameter.VAR_KEYWORD for param in params) or any(
        param.name == "verify_host_key" for param in params
    ):
        kwargs["verify_host_key"] = p["verify_host_key"]
    return client_cls(**kwargs)


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


def _prompt_default(value: str, secret: bool = False) -> str:
    if not value:
        return "None"
    if secret:
        return "****"
    return value


def _prompt_text(label: str, value: str, secret: bool = False) -> str:
    return f"{label} [{_prompt_default(value, secret=secret)}]"


def _prompt_string(label: str, value: str, secret: bool = False) -> str:
    return click.prompt(
        _prompt_text(label, value, secret=secret),
        default=value,
        hide_input=secret,
        show_default=False,
        type=str,
    )


def _prompt_port(value: str) -> str:
    while True:
        port_text = click.prompt(
            _prompt_text("Port", value),
            default=value,
            show_default=False,
            type=str,
        ).strip()
        try:
            port = int(port_text)
        except ValueError:
            err_console.print("[red]Port must be an integer.[/red]")
            value = port_text or value
            continue
        if port < 1 or port > 65535:
            err_console.print("[red]Port must be between 1 and 65535.[/red]")
            value = port_text
            continue
        return str(port)


def _prompt_transport(value: str) -> str:
    return click.prompt(
        _prompt_text("Transport", value),
        default=value,
        show_default=False,
        type=click.Choice(TRANSPORT_CHOICES, case_sensitive=False),
    )


def _run_host_command(
def _run_host_command(
    cmd: list[str],
    ssh_host: str = "",
    ssh_user: str = "root",
    *,
    verify_host_key: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run *cmd* locally or over SSH if *ssh_host* is set."""
    if not ssh_host:
        return subprocess.run(cmd, capture_output=True, text=True)

    target = f"{ssh_user}@{ssh_host}" if ssh_user else ssh_host
    remote_cmd = " ".join(shlex.quote(c) for c in cmd)
    full_cmd = ["ssh"]
    if not verify_host_key:
        full_cmd += [
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
        ]
    full_cmd += [target, remote_cmd]
    return subprocess.run(full_cmd, capture_output=True, text=True)


def _require_tcp_agent(client: XPClient, feature: str) -> None:
    """Raise ``ClickException`` if *client* is not using the TCP transport."""
    if isinstance(getattr(client, "_transport", None), TCPTransport):
        return
    raise click.ClickException(
        f"{feature} requires the TCP agent transport. Start the agent or pass --transport tcp."
    )
