"""CLI for xpctl."""

from __future__ import annotations

import csv
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import click
from rich.console import Console
from rich.table import Table

from xpctl.client import XPClient
from xpctl.config import DEFAULT_PROFILE, load_profile, save_profile
from xpctl.debuggers import DEBUGGER_DESCRIPTIONS
from xpctl.deploy import AgentDeployer
from xpctl.resources import read_remote_script
from xpctl.transport.ssh import SSHTransport

console = Console()
err_console = Console(stderr=True)
JSON_MARKER = "__XPSH_JSON__"
TRANSPORT_CHOICES = ("auto", "tcp", "ssh")
RUNTIME_DEFAULT_PORT = 9578
CONFIGURE_DEFAULT_PORT = "22"
CONFIGURE_DEFAULT_TRANSPORT = "auto"

# ---------------------------------------------------------------------------
# Shared options
# ---------------------------------------------------------------------------

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
]


def common_options(fn):
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
) -> dict[str, str | int]:
    saved = load_profile(profile_name)

    resolved_host = host if host is not None else (saved.get("hostname") or "")
    saved_port = saved.get("port", "")
    resolved_port = port if port is not None else int(saved_port or RUNTIME_DEFAULT_PORT)
    resolved_transport = (
        transport_mode
        if transport_mode is not None
        else (saved.get("transport") or CONFIGURE_DEFAULT_TRANSPORT)
    )
    resolved_user = user if user is not None else saved.get("username", "")
    resolved_password = (
        password if password is not None else saved.get("password", "")
    )

    return {
        "profile": profile_name,
        "host": resolved_host,
        "port": resolved_port,
        "transport_mode": resolved_transport,
        "user": resolved_user,
        "password": resolved_password,
    }


def _client(ctx: click.Context) -> XPClient:
    """Build an XPClient from the root context params."""
    p = ctx.ensure_object(dict)
    return XPClient(
        host=p["host"],
        port=p["port"],
        transport=p["transport_mode"],
        password=p["password"],
        user=p["user"],
    )


def _default_remote_download_dir() -> str:
    return r"C:\xpctl\downloads"


def _exe_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name
    if not name:
        return "download.exe"
    if not name.lower().endswith(".exe"):
        return f"{name}.exe"
    return name


def _print_exec_result(result: dict, ctx: click.Context | None = None) -> None:
    if result.get("stdout"):
        console.print(result["stdout"], end="", highlight=False)
    if result.get("stderr"):
        err_console.print(result["stderr"], end="", highlight=False)
    if ctx is not None:
        ctx.exit(result.get("returncode", 0))


def _ensure_success(result: dict, action: str) -> None:
    if result.get("returncode", 0) != 0:
        raise click.ClickException(
            f"{action} failed (rc={result.get('returncode')}): {result.get('stderr', '').strip()}"
        )


def _exec_python_json(
    client: XPClient,
    script: str,
    payload: dict | None = None,
    timeout: int = 60,
):
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


def _cmd_quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


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


def _attempt_profile_connection(values: dict[str, str]) -> None:
    client = XPClient(
        host=values["hostname"],
        port=int(values["port"]),
        transport=values["transport"],
        user=values["username"],
        password=values["password"],
    )
    try:
        client.connect()
        if not client.ping():
            raise ConnectionError("Connection opened but ping failed")
    finally:
        client.disconnect()


def _run_host_command(
    cmd: list[str],
    ssh_host: str = "",
    ssh_user: str = "root",
) -> subprocess.CompletedProcess[str]:
    full_cmd = cmd

    if ssh_host:
        target = f"{ssh_user}@{ssh_host}" if ssh_user else ssh_host
        full_cmd = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            target,
            *cmd,
        ]

    return subprocess.run(full_cmd, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------


@click.group()
@common_options
@click.pass_context
def main(ctx, profile, host, port, transport_mode, password, user):
    """xpctl — Remote management toolkit for Windows XP VM."""
    resolved = _resolve_connection_settings(
        profile_name=profile,
        host=host,
        port=port,
        transport_mode=transport_mode,
        user=user,
        password=password,
    )
    ctx.ensure_object(dict).update(resolved)
    if ctx.invoked_subcommand and ctx.invoked_subcommand != "configure" and not resolved["host"]:
        raise click.UsageError(
            "Missing host. Provide --host, set XPCTL_HOST, or run `xpctl configure`."
        )


# ---------------------------------------------------------------------------
# configure
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--profile",
    "configure_profile",
    default=None,
    help="Profile name to configure.",
)
@click.pass_context
def configure(ctx, configure_profile):
    """Interactively configure a saved connection profile."""
    profile_name = configure_profile or ctx.ensure_object(dict).get(
        "profile", DEFAULT_PROFILE
    )
    saved = load_profile(profile_name)
    values = {
        "hostname": saved.get("hostname", ""),
        "port": saved.get("port", CONFIGURE_DEFAULT_PORT) or CONFIGURE_DEFAULT_PORT,
        "transport": (
            saved.get("transport", CONFIGURE_DEFAULT_TRANSPORT)
            or CONFIGURE_DEFAULT_TRANSPORT
        ),
        "username": saved.get("username", ""),
        "password": saved.get("password", ""),
    }

    while True:
        values["hostname"] = _prompt_string("Hostname or IP", values["hostname"])
        values["port"] = _prompt_port(values["port"])
        values["username"] = _prompt_string("Username", values["username"])
        values["password"] = _prompt_string(
            "Password", values["password"], secret=True
        )
        values["transport"] = _prompt_transport(values["transport"])

        try:
            _attempt_profile_connection(values)
        except Exception as exc:
            err_console.print(f"[red]Connection failed:[/red] {exc}")
            continue

        path = save_profile(profile_name, values)
        console.print(
            f"[green]Connection successful.[/green] Saved profile '{profile_name}' to {path}"
        )
        return


# ---------------------------------------------------------------------------
# ping
# ---------------------------------------------------------------------------


@main.command()
@click.pass_context
def ping(ctx):
    """Check if the agent is alive."""
    client = _client(ctx)
    try:
        client.connect()
        ok = client.ping()
    except Exception:
        ok = False
    finally:
        client.disconnect()

    if ok:
        console.print("[green]Agent is alive[/green]")
    else:
        err_console.print("[red]Agent is unreachable[/red]")
        ctx.exit(1)


# ---------------------------------------------------------------------------
# exec
# ---------------------------------------------------------------------------


@main.command("exec")
@click.argument("cmd", nargs=-1, required=True)
@click.option("--timeout", default=30, type=int)
@click.option("--python", "use_python", is_flag=True, help="Execute as Python code")
@click.pass_context
def exec_cmd(ctx, cmd, timeout, use_python):
    """Execute a remote command."""
    cmd_str = " ".join(cmd)
    with _client(ctx) as client:
        if use_python:
            result = client.exec_python(cmd_str, timeout)
        else:
            result = client.exec(cmd_str, timeout)

    if result.get("stdout"):
        console.print(result["stdout"], end="", highlight=False)
    if result.get("stderr"):
        err_console.print(result["stderr"], end="", highlight=False)
    ctx.exit(result.get("returncode", 0))


# ---------------------------------------------------------------------------
# bat  (batch files)
# ---------------------------------------------------------------------------


@main.group()
def bat():
    """Batch file operations."""


@bat.command("run")
@click.argument("path")
@click.argument("args", nargs=-1)
@click.option("--timeout", default=60, type=int)
@click.pass_context
def bat_run(ctx, path, args, timeout):
    """Run a .bat file on XP."""
    with _client(ctx) as client:
        result = client.bat_run(path, args=list(args), timeout=timeout)

    if result.get("stdout"):
        console.print(result["stdout"], end="", highlight=False)
    if result.get("stderr"):
        err_console.print(result["stderr"], end="", highlight=False)
    ctx.exit(result.get("returncode", 0))


@bat.command("push-run")
@click.argument("local_path", type=click.Path(exists=True))
@click.argument("args", nargs=-1)
@click.option("--timeout", default=60, type=int)
@click.pass_context
def bat_push_run(ctx, local_path, args, timeout):
    """Upload and execute a local .bat file on XP."""
    with _client(ctx) as client:
        result = client.bat_push_run(local_path, args=list(args), timeout=timeout)

    if result.get("stdout"):
        console.print(result["stdout"], end="", highlight=False)
    if result.get("stderr"):
        err_console.print(result["stderr"], end="", highlight=False)
    ctx.exit(result.get("returncode", 0))


@bat.command("create")
@click.argument("remote_path")
@click.argument("commands", nargs=-1, required=True)
@click.pass_context
def bat_create(ctx, remote_path, commands):
    """Create a .bat file on XP from inline commands."""
    with _client(ctx) as client:
        result = client.bat_create(remote_path, list(commands))
    console.print(f"[green]Created {result['path']}[/green]")


# ---------------------------------------------------------------------------
# debug  (debugger integration)
# ---------------------------------------------------------------------------


@main.group()
def debug():
    """Debugger integration (OllyDbg, WinDbg/CDB, x64dbg)."""


@debug.command("list")
@click.pass_context
def debug_list(ctx):
    """List debuggers installed on XP."""
    with _client(ctx) as client:
        installed = client.debug.list()

    if not installed:
        console.print("[yellow]No debuggers detected on XP.[/yellow]")
        return

    table = Table(title="Installed Debuggers")
    table.add_column("Name", style="cyan")
    table.add_column("Path", style="green")
    table.add_column("Description")

    for name, path in sorted(installed.items()):
        desc = DEBUGGER_DESCRIPTIONS.get(name, "")
        table.add_row(name, path, desc)

    console.print(table)


@debug.command("ps")
@click.option("--filter", "filter_str", default="")
@click.pass_context
def debug_ps(ctx, filter_str):
    """List debuggable processes on XP."""
    with _client(ctx) as client:
        procs = client.processes(filter_str)

    table = Table(title="Processes")
    table.add_column("PID", style="cyan", justify="right")
    table.add_column("Name", style="green")
    table.add_column("Memory")

    for p in procs:
        table.add_row(str(p.get("pid", "?")), p.get("name", "?"), p.get("memory", ""))

    console.print(table)


# -- olly ------------------------------------------------------------------


@debug.group()
def olly():
    """OllyDbg commands."""


@olly.command("launch")
@click.argument("exe_path")
@click.pass_context
def olly_launch(ctx, exe_path):
    """Launch OllyDbg with a target executable."""
    with _client(ctx) as client:
        sid = client.debug.olly.launch(exe_path)
    console.print(f"[green]Session started:[/green] {sid}")


@olly.command("attach")
@click.argument("pid", type=int)
@click.pass_context
def olly_attach(ctx, pid):
    """Attach OllyDbg to a running process."""
    with _client(ctx) as client:
        sid = client.debug.olly.attach(pid)
    console.print(f"[green]Attached:[/green] {sid}")


@olly.command("run-script")
@click.argument("script_path")
@click.option("--session", "session_id", required=True, help="Session ID")
@click.pass_context
def olly_run_script(ctx, script_path, session_id):
    """Execute an OllyScript (.osc) file."""
    with _client(ctx) as client:
        output = client.debug.olly.run_script(session_id, script_path)
    console.print(output, highlight=False)


@olly.command("log")
@click.option("--session", "session_id", required=True, help="Session ID")
@click.pass_context
def olly_log(ctx, session_id):
    """Retrieve OllyDbg log output."""
    with _client(ctx) as client:
        output = client.debug.olly.log(session_id)
    console.print(output, highlight=False)


@olly.command("detach")
@click.option("--session", "session_id", required=True, help="Session ID")
@click.pass_context
def olly_detach(ctx, session_id):
    """Close an OllyDbg session."""
    with _client(ctx) as client:
        client.debug.olly.detach(session_id)
    console.print("[green]Session closed.[/green]")


# -- windbg ----------------------------------------------------------------


@debug.group()
def windbg():
    """WinDbg / CDB commands."""


@windbg.command("launch")
@click.argument("exe_path")
@click.pass_context
def windbg_launch(ctx, exe_path):
    """Launch CDB (command-line WinDbg) with a target."""
    with _client(ctx) as client:
        sid = client.debug.windbg.launch(exe_path)
    console.print(f"[green]Session started:[/green] {sid}")


@windbg.command("attach")
@click.argument("pid", type=int)
@click.pass_context
def windbg_attach(ctx, pid):
    """Attach CDB to a running process."""
    with _client(ctx) as client:
        sid = client.debug.windbg.attach(pid)
    console.print(f"[green]Attached:[/green] {sid}")


@windbg.command("cmd")
@click.argument("command")
@click.option("--session", "session_id", required=True, help="Session ID")
@click.pass_context
def windbg_cmd(ctx, command, session_id):
    """Send a debugger command to a CDB session."""
    with _client(ctx) as client:
        output = client.debug.windbg.cmd(session_id, command)
    console.print(output, highlight=False)


@windbg.command("analyze")
@click.argument("dump_path")
@click.pass_context
def windbg_analyze(ctx, dump_path):
    """Analyze a crash dump with CDB."""
    with _client(ctx) as client:
        sid = client.debug.windbg.launch(dump_path)
        output = client.debug.windbg.cmd(sid, "!analyze -v")
        client.debug.windbg.detach(sid)
    console.print(output, highlight=False)


@windbg.command("detach")
@click.option("--session", "session_id", required=True, help="Session ID")
@click.pass_context
def windbg_detach(ctx, session_id):
    """Close a CDB session."""
    with _client(ctx) as client:
        client.debug.windbg.detach(session_id)
    console.print("[green]Session closed.[/green]")


# -- x64dbg ----------------------------------------------------------------


@debug.group()
def x64dbg():
    """x32dbg / x64dbg commands."""


@x64dbg.command("launch")
@click.argument("exe_path")
@click.pass_context
def x64dbg_launch(ctx, exe_path):
    """Launch x32dbg with a target executable."""
    with _client(ctx) as client:
        sid = client.debug.x64dbg.launch(exe_path)
    console.print(f"[green]Session started:[/green] {sid}")


@x64dbg.command("attach")
@click.argument("pid", type=int)
@click.pass_context
def x64dbg_attach(ctx, pid):
    """Attach x32dbg to a running process."""
    with _client(ctx) as client:
        sid = client.debug.x64dbg.attach(pid)
    console.print(f"[green]Attached:[/green] {sid}")


@x64dbg.command("cmd")
@click.argument("command")
@click.option("--session", "session_id", required=True, help="Session ID")
@click.pass_context
def x64dbg_cmd(ctx, command, session_id):
    """Send a command to an x32dbg session."""
    with _client(ctx) as client:
        output = client.debug.x64dbg.cmd(session_id, command)
    console.print(output, highlight=False)


@x64dbg.command("run-script")
@click.argument("script_path")
@click.option("--session", "session_id", required=True, help="Session ID")
@click.pass_context
def x64dbg_run_script(ctx, script_path, session_id):
    """Execute an x64dbg script file."""
    with _client(ctx) as client:
        output = client.debug.x64dbg.run_script(session_id, script_path)
    console.print(output, highlight=False)


@x64dbg.command("detach")
@click.option("--session", "session_id", required=True, help="Session ID")
@click.pass_context
def x64dbg_detach(ctx, session_id):
    """Close an x32dbg session."""
    with _client(ctx) as client:
        client.debug.x64dbg.detach(session_id)
    console.print("[green]Session closed.[/green]")


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------


@main.command()
@click.argument("local_path", type=click.Path(exists=True))
@click.argument("remote_path")
@click.pass_context
def upload(ctx, local_path, remote_path):
    """Upload a file to XP."""
    with _client(ctx) as client:
        result = client.upload(local_path, remote_path)
    console.print(
        f"[green]Uploaded {result.get('bytes_written', '?')} bytes to {remote_path}[/green]"
    )


@main.command("fetch-exe")
@click.argument("url")
@click.option("--name", help="Output filename on XP (defaults from URL).")
@click.option(
    "--remote-dir",
    default="",
    help="Remote destination directory (default: XP user's Desktop).",
)
@click.option("--timeout", default=120, type=int, show_default=True)
@click.pass_context
def fetch_exe(ctx, url, name, remote_dir, timeout):
    """Download an EXE URL locally and upload it to the XP Desktop."""
    filename = name or _exe_filename_from_url(url)
    destination_dir = remote_dir or _default_remote_download_dir()
    destination_root = destination_dir.rstrip("\\/")
    destination = f"{destination_root}\\{filename}"

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="xpctl_", suffix=".exe", delete=False
        ) as tmp:
            tmp_path = Path(tmp.name)

        console.print(f"[cyan]Downloading:[/cyan] {url}")
        req = Request(url, headers={"User-Agent": "xpctl/0.1"})
        with urlopen(req, timeout=timeout) as resp, tmp_path.open("wb") as out:
            shutil.copyfileobj(resp, out)

        size = tmp_path.stat().st_size
        if size == 0:
            raise click.ClickException("Downloaded file is empty.")

        with _client(ctx) as client:
            client.exec(f'if not exist "{destination_dir}" mkdir "{destination_dir}"')
            result = client.upload(tmp_path, destination)

        console.print(
            f"[green]Uploaded {result.get('bytes_written', size)} bytes to {destination}[/green]"
        )
    except URLError as exc:
        raise click.ClickException(f"Download failed: {exc}") from exc
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


@main.command()
@click.argument("remote_path")
@click.argument("local_path", type=click.Path())
@click.pass_context
def download(ctx, remote_path, local_path):
    """Download a file from XP."""
    with _client(ctx) as client:
        result = client.download(remote_path, local_path)
    console.print(
        f"[green]Downloaded {result['size']} bytes to {result['path']}[/green]"
    )


@main.command()
@click.argument("path", default=".")
@click.option("-r", "--recursive", is_flag=True)
@click.pass_context
def ls(ctx, path, recursive):
    """List a remote directory."""
    with _client(ctx) as client:
        entries = client.ls(path, recursive)

    table = Table(title=f"Directory: {path}")
    table.add_column("Type", style="cyan", width=4)
    table.add_column("Size", justify="right", style="green")
    table.add_column("Name")

    for e in entries:
        t = "DIR" if e.get("type") == "dir" else "FILE"
        size = str(e.get("size", "")) if e.get("type") != "dir" else ""
        table.add_row(t, size, e.get("name", ""))

    console.print(table)


@main.command()
@click.argument("path")
@click.option("-r", "--recursive", is_flag=True)
@click.pass_context
def rm(ctx, path, recursive):
    """Delete a remote file or directory."""
    with _client(ctx) as client:
        client.rm(path, recursive)
    console.print(f"[green]Deleted: {path}[/green]")


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------


@main.command()
@click.pass_context
def sysinfo(ctx):
    """Show XP system information."""
    with _client(ctx) as client:
        info = client.sysinfo()

    table = Table(title="System Information")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")

    for k, v in sorted(info.items()):
        table.add_row(k, str(v))

    console.print(table)


@main.command()
@click.option("--filter", "filter_str", default="")
@click.pass_context
def ps(ctx, filter_str):
    """List processes on XP."""
    with _client(ctx) as client:
        procs = client.processes(filter_str)

    table = Table(title="Processes")
    table.add_column("PID", style="cyan", justify="right")
    table.add_column("Name", style="green")
    table.add_column("Memory")

    for p in procs:
        table.add_row(str(p.get("pid", "?")), p.get("name", "?"), p.get("memory", ""))

    console.print(table)


# ---------------------------------------------------------------------------
# push-run
# ---------------------------------------------------------------------------


@main.command("push-run")
@click.argument("script", type=click.Path(exists=True))
@click.option("--timeout", default=60, type=int)
@click.pass_context
def push_run(ctx, script, timeout):
    """Upload and execute a script (.py or .bat) on XP."""
    with _client(ctx) as client:
        result = client.push_and_run(script, timeout=timeout)

    if result.get("stdout"):
        console.print(result["stdout"], end="", highlight=False)
    if result.get("stderr"):
        err_console.print(result["stderr"], end="", highlight=False)
    ctx.exit(result.get("returncode", 0))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@main.group()
def reg():
    """Registry operations."""


@reg.command("read")
@click.argument("key")
@click.option("--value", "value_name", default="", help="Value name within the key.")
@click.option("--timeout", default=30, type=int)
@click.pass_context
def reg_read(ctx, key, value_name, timeout):
    """Read a registry key/value."""
    cmd = f"reg query {_cmd_quote(key)}"
    if value_name:
        cmd += f" /v {_cmd_quote(value_name)}"
    with _client(ctx) as client:
        result = client.exec(cmd, timeout=timeout)
    _print_exec_result(result, ctx)


@reg.command("write")
@click.argument("key")
@click.argument("name")
@click.argument("data")
@click.option("--type", "value_type", default="REG_SZ", show_default=True)
@click.option("--force", is_flag=True, help="Overwrite existing value.")
@click.option("--timeout", default=30, type=int)
@click.pass_context
def reg_write(ctx, key, name, data, value_type, force, timeout):
    """Write a registry value."""
    cmd = (
        f"reg add {_cmd_quote(key)} /v {_cmd_quote(name)} "
        f"/t {value_type} /d {_cmd_quote(data)}"
    )
    if force:
        cmd += " /f"
    with _client(ctx) as client:
        result = client.exec(cmd, timeout=timeout)
    _print_exec_result(result, ctx)


@reg.command("delete")
@click.argument("key")
@click.option("--value", "value_name", default="", help="Delete only this value name.")
@click.option("--force", is_flag=True, help="Skip confirmation.")
@click.option("--timeout", default=30, type=int)
@click.pass_context
def reg_delete(ctx, key, value_name, force, timeout):
    """Delete a registry key or value."""
    cmd = f"reg delete {_cmd_quote(key)}"
    if value_name:
        cmd += f" /v {_cmd_quote(value_name)}"
    if force:
        cmd += " /f"
    with _client(ctx) as client:
        result = client.exec(cmd, timeout=timeout)
    _print_exec_result(result, ctx)


@reg.command("export")
@click.argument("key")
@click.argument("local_path", type=click.Path())
@click.option("--timeout", default=60, type=int)
@click.pass_context
def reg_export(ctx, key, local_path, timeout):
    """Export a registry key and pull the .reg file locally."""
    remote_tmp = r"C:\xpctl\tmp\reg_export_{0}.reg".format(int(time.time() * 1000))
    with _client(ctx) as client:
        client.exec(
            r'if not exist "C:\xpctl\tmp" mkdir "C:\xpctl\tmp"', timeout=timeout
        )
        result = client.exec(
            f"reg export {_cmd_quote(key)} {_cmd_quote(remote_tmp)} /y",
            timeout=timeout,
        )
        _ensure_success(result, "reg export")
        client.download(remote_tmp, local_path)
        try:
            client.rm(remote_tmp)
        except Exception:
            pass
    console.print(f"[green]Exported registry key to {local_path}[/green]")


# ---------------------------------------------------------------------------
# DLL / COM
# ---------------------------------------------------------------------------


@main.group()
def dll():
    """DLL helpers."""


@dll.command("list")
@click.argument("pid", type=int)
@click.option("--timeout", default=30, type=int)
@click.pass_context
def dll_list(ctx, pid, timeout):
    """List DLL modules loaded by a process (tasklist /m)."""
    cmd = f'tasklist /m /fi "PID eq {pid}" /fo csv /nh'
    with _client(ctx) as client:
        result = client.exec(cmd, timeout=timeout)
    _ensure_success(result, "dll list")
    table = Table(title=f"Loaded DLLs for PID {pid}")
    table.add_column("Process", style="cyan")
    table.add_column("PID", style="green")
    table.add_column("Modules")
    lines = [entry for entry in result.get("stdout", "").splitlines() if entry.strip()]
    for line in lines:
        row = next(csv.reader([line]), [])
        if len(row) >= 3:
            table.add_row(row[0], row[1], row[2])
    console.print(table)


@dll.command("inject")
@click.argument("pid", type=int)
@click.argument("dll_path")
@click.option("--timeout", default=60, type=int)
@click.pass_context
def dll_inject(ctx, pid, dll_path, timeout):
    """Inject a DLL via CreateRemoteThread + LoadLibraryA."""
    script = read_remote_script("dll_inject")
    with _client(ctx) as client:
        data = _exec_python_json(
            client,
            script,
            payload={"pid": pid, "dll_path": dll_path},
            timeout=timeout,
        )
    console.print(f"[green]Injected:[/green] {data}")


@dll.command("regsvr32")
@click.argument("dll_path")
@click.option(
    "--unregister", is_flag=True, help="Unregister DLL instead of registering."
)
@click.option("--timeout", default=60, type=int)
@click.pass_context
def dll_regsvr32(ctx, dll_path, unregister, timeout):
    """Register/unregister COM DLL with regsvr32."""
    mode = "/u " if unregister else ""
    cmd = f"regsvr32 /s {mode}{_cmd_quote(dll_path)}"
    with _client(ctx) as client:
        result = client.exec(cmd, timeout=timeout)
    _print_exec_result(result, ctx)


@main.group()
def com():
    """COM registration helpers."""


@com.command("list")
@click.option("--filter", "filter_str", default="", help="Filter string for reg query.")
@click.option("--timeout", default=60, type=int)
@click.pass_context
def com_list(ctx, filter_str, timeout):
    """List COM CLSID registrations."""
    cmd = r"reg query HKCR\CLSID /s"
    if filter_str:
        cmd += f" /f {_cmd_quote(filter_str)}"
    with _client(ctx) as client:
        result = client.exec(cmd, timeout=timeout)
    _print_exec_result(result, ctx)


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


@main.group()
def mem():
    """Memory inspection helpers."""


@mem.command("dump")
@click.argument("pid", type=int)
@click.argument("local_path", type=click.Path())
@click.option("--remote-path", default="", help="Optional remote dump path.")
@click.option("--timeout", default=120, type=int)
@click.pass_context
def memdump(ctx, pid, local_path, remote_path, timeout):
    """Create a MiniDump for a process and pull it locally."""
    remote_dump = remote_path or r"C:\xpctl\tmp\mem_{0}.dmp".format(pid)
    script = read_remote_script("memdump")
    with _client(ctx) as client:
        data = _exec_python_json(
            client,
            script,
            payload={"pid": pid, "dump_path": remote_dump},
            timeout=timeout,
        )
        client.download(remote_dump, local_path)
    console.print(
        f"[green]Dumped PID {pid} -> {local_path} ({data.get('size', '?')} bytes)[/green]"
    )


@mem.command("read")
@click.argument("pid", type=int)
@click.argument("address")
@click.argument("size", type=int)
@click.option("--timeout", default=60, type=int)
@click.pass_context
def mem_read(ctx, pid, address, size, timeout):
    """Read process memory and return hex bytes."""
    script = read_remote_script("mem_read")
    with _client(ctx) as client:
        data = _exec_python_json(
            client,
            script,
            payload={"pid": pid, "address": address, "size": size},
            timeout=timeout,
        )
    console.print(data["hex"])


# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------


@main.group()
def net():
    """Network utilities."""


@net.command("netstat")
@click.option("--timeout", default=30, type=int)
@click.pass_context
def net_netstat(ctx, timeout):
    """Show netstat with PID mapping."""
    with _client(ctx) as client:
        result = client.exec("netstat -ano", timeout=timeout)
    _ensure_success(result, "netstat")

    table = Table(title="Netstat")
    table.add_column("Proto", style="cyan")
    table.add_column("Local")
    table.add_column("Remote")
    table.add_column("State", style="green")
    table.add_column("PID", justify="right")

    for line in result.get("stdout", "").splitlines():
        line = line.strip()
        if not line or not (line.startswith("TCP") or line.startswith("UDP")):
            continue
        parts = line.split()
        if parts[0] == "TCP" and len(parts) >= 5:
            table.add_row(parts[0], parts[1], parts[2], parts[3], parts[4])
        elif parts[0] == "UDP" and len(parts) >= 4:
            table.add_row(parts[0], parts[1], parts[2], "", parts[3])
    console.print(table)


@net.command("portfwd")
@click.argument("local_port", type=int)
@click.argument("remote_host")
@click.argument("remote_port", type=int)
@click.option("--background/--foreground", default=True, show_default=True)
@click.pass_context
def net_portfwd(ctx, local_port, remote_host, remote_port, background):
    """Create an SSH local port-forward tunnel."""
    p = ctx.ensure_object(dict)
    cmd = [
        "ssh",
        "-N",
        "-L",
        f"{local_port}:{remote_host}:{remote_port}",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        f"{p['user']}@{p['host']}",
    ]
    if background:
        proc = subprocess.Popen(cmd)
        console.print(
            f"[green]Port forward started:[/green] localhost:{local_port} -> {remote_host}:{remote_port} (pid {proc.pid})"
        )
    else:
        subprocess.run(cmd, check=False)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------


@main.group()
def gui():
    """GUI/screenshot automation helpers."""


@gui.command("screenshot")
@click.argument("local_path", type=click.Path())
@click.option("--remote-path", default=r"C:\xpctl\tmp\screenshot.bmp")
@click.option("--timeout", default=90, type=int)
@click.pass_context
def gui_screenshot(ctx, local_path, remote_path, timeout):
    """Capture desktop screenshot to BMP and download it."""
    script = read_remote_script("gui_screenshot")
    with _client(ctx) as client:
        _exec_python_json(
            client, script, payload={"path": remote_path}, timeout=timeout
        )
        client.download(remote_path, local_path)
    console.print(f"[green]Screenshot saved:[/green] {local_path}")


@gui.command("window-list")
@click.option("--timeout", default=30, type=int)
@click.pass_context
def gui_window_list(ctx, timeout):
    """List top-level windows."""
    script = read_remote_script("gui_window_list")
    with _client(ctx) as client:
        data = _exec_python_json(client, script, timeout=timeout)

    table = Table(title="Top-Level Windows")
    table.add_column("HWND", style="cyan")
    table.add_column("Class", style="green")
    table.add_column("Title")
    for w in data.get("windows", []):
        table.add_row(hex(int(w["hwnd"])), w.get("class", ""), w.get("title", ""))
    console.print(table)


@gui.command("sendkeys")
@click.argument("keys")
@click.option("--title", default="", help="Focus this exact window title first.")
@click.option("--timeout", default=30, type=int)
@click.pass_context
def gui_sendkeys(ctx, keys, title, timeout):
    """Send keyboard input (ASCII-focused helper)."""
    script = read_remote_script("gui_sendkeys")
    with _client(ctx) as client:
        data = _exec_python_json(
            client,
            script,
            payload={"keys": keys, "title": title},
            timeout=timeout,
        )
    console.print(f"[green]Sent keys:[/green] {data['sent']}")


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


@main.group()
def svc():
    """Service control helpers."""


@svc.command("list")
@click.pass_context
def svc_list(ctx):
    """List running services."""
    with _client(ctx) as client:
        result = client.services("list")
    for name in result.get("services", []):
        console.print(name, highlight=False)


@svc.command("start")
@click.argument("name")
@click.pass_context
def svc_start(ctx, name):
    """Start a service."""
    with _client(ctx) as client:
        result = client.services("start", name)
    _print_exec_result(result, ctx)


@svc.command("stop")
@click.argument("name")
@click.pass_context
def svc_stop(ctx, name):
    """Stop a service."""
    with _client(ctx) as client:
        result = client.services("stop", name)
    _print_exec_result(result, ctx)


@svc.command("status")
@click.argument("name")
@click.pass_context
def svc_status(ctx, name):
    """Show service status."""
    with _client(ctx) as client:
        result = client.exec(f"sc query {_cmd_quote(name)}", timeout=30)
    _print_exec_result(result, ctx)


# ---------------------------------------------------------------------------
# Scripting helpers
# ---------------------------------------------------------------------------


@main.command("script")
@click.argument("script_path", type=click.Path(exists=True))
@click.pass_context
def script_run(ctx, script_path):
    """Run a local Python script with `client` injected."""
    source = Path(script_path).read_text()
    with _client(ctx) as client:
        globs = {
            "__name__": "__main__",
            "__file__": script_path,
            "client": client,
            "console": console,
            "err_console": err_console,
        }
        exec(compile(source, script_path, "exec"), globs, globs)


@main.command("shell")
@click.option("--session", "session_id", default="default", help="Shell session ID.")
@click.pass_context
def shell_cmd(ctx, session_id):
    """Interactive remote Python 3.4 shell on the XP machine."""
    try:
        import readline  # noqa: F401
    except ImportError:
        pass

    with _client(ctx) as client:
        info = client.agent_info()
        py_ver = info.get("python", "?")
        console.print(
            f"[green]Remote Python {py_ver} shell[/green] (session={session_id}). "
            "Ctrl-D to exit, %reset to clear namespace."
        )

        prompt1 = ">>> "
        prompt2 = "... "
        more = False
        buf = []

        while True:
            try:
                line = input(prompt2 if more else prompt1)
            except EOFError:
                console.print("\n[yellow]Disconnected.[/yellow]")
                break
            except KeyboardInterrupt:
                console.print("\nKeyboardInterrupt")
                more = False
                buf = []
                continue

            if not more and line.strip() == "%reset":
                client.pyshell_reset(session_id)
                console.print("[green]Namespace reset.[/green]")
                continue

            buf.append(line)

            result = client.pyshell_eval(line, session_id)
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            more = result.get("more", False)

            if stdout:
                console.print(stdout, end="", highlight=False)
            if stderr:
                err_console.print(stderr, end="", highlight=False)

            if not more:
                buf = []


@main.command("watch")
@click.argument("cmd", nargs=-1, required=True)
@click.option("--interval", default=2.0, type=float, show_default=True)
@click.option("--count", default=0, type=int, help="0 means run forever.")
@click.option("--timeout", default=30, type=int)
@click.pass_context
def watch_cmd(ctx, cmd, interval, count, timeout):
    """Repeat a command at an interval."""
    cmd_str = " ".join(cmd)
    runs = 0
    try:
        while True:
            runs += 1
            console.print(f"[cyan][{runs}] {time.ctime()}[/cyan]")
            with _client(ctx) as client:
                result = client.exec(cmd_str, timeout=timeout)
            _print_exec_result(result)
            if count and runs >= count:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/yellow]")


# ---------------------------------------------------------------------------
# File extras
# ---------------------------------------------------------------------------


@main.command("cat")
@click.argument("remote_path")
@click.option("--timeout", default=30, type=int)
@click.pass_context
def cat_cmd(ctx, remote_path, timeout):
    """Print a remote file."""
    with _client(ctx) as client:
        result = client.exec(f"type {_cmd_quote(remote_path)}", timeout=timeout)
    _print_exec_result(result, ctx)


@main.command("head")
@click.argument("remote_path")
@click.option("-n", "--lines", default=20, type=int, show_default=True)
@click.option("--timeout", default=30, type=int)
@click.pass_context
def head_cmd(ctx, remote_path, lines, timeout):
    """Print first N lines from a remote file."""
    script = read_remote_script("head")
    with _client(ctx) as client:
        data = _exec_python_json(
            client,
            script,
            payload={"path": remote_path, "lines": lines},
            timeout=timeout,
        )
    console.print(data.get("text", ""), highlight=False)


@main.command("tail")
@click.argument("remote_path")
@click.option("-n", "--lines", default=20, type=int, show_default=True)
@click.option("--timeout", default=30, type=int)
@click.pass_context
def tail_cmd(ctx, remote_path, lines, timeout):
    """Print last N lines from a remote file."""
    script = read_remote_script("tail")
    with _client(ctx) as client:
        data = _exec_python_json(
            client,
            script,
            payload={"path": remote_path, "lines": lines},
            timeout=timeout,
        )
    console.print(data.get("text", ""), highlight=False)


@main.command("find")
@click.argument("remote_path")
@click.option("--glob", "glob_pattern", default="*", show_default=True)
@click.option(
    "--regex", "regex_pattern", default="", help="Optional regex on full path."
)
@click.option("--timeout", default=60, type=int)
@click.pass_context
def find_cmd(ctx, remote_path, glob_pattern, regex_pattern, timeout):
    """Find files recursively by glob/regex."""
    script = read_remote_script("find")
    with _client(ctx) as client:
        data = _exec_python_json(
            client,
            script,
            payload={"root": remote_path, "glob": glob_pattern, "regex": regex_pattern},
            timeout=timeout,
        )
    for match in data.get("matches", []):
        console.print(match, highlight=False)


@main.command("checksum")
@click.argument("remote_path")
@click.option("--algo", default="md5", type=click.Choice(["md5", "sha1", "sha256"]))
@click.option("--timeout", default=30, type=int)
@click.pass_context
def checksum_cmd(ctx, remote_path, algo, timeout):
    """Calculate remote file checksum."""
    script = read_remote_script("checksum")
    with _client(ctx) as client:
        data = _exec_python_json(
            client,
            script,
            payload={"path": remote_path, "algo": algo},
            timeout=timeout,
        )
    console.print(f"{data['algo']} {data['hexdigest']}  {remote_path}")


@main.command("edit")
@click.argument("remote_path")
@click.option("--editor", default="", help="Override $EDITOR.")
@click.pass_context
def edit_cmd(ctx, remote_path, editor):
    """Edit a remote file with your local editor and push back."""
    editor_cmd = editor or os.environ.get("EDITOR")
    if not editor_cmd:
        raise click.ClickException("Set $EDITOR or pass --editor")

    tmp_file = tempfile.NamedTemporaryFile(delete=False)
    tmp_file.close()
    tmp_path = Path(tmp_file.name)
    try:
        with _client(ctx) as client:
            client.download(remote_path, tmp_path)
        before = tmp_path.read_bytes()
        subprocess.run(shlex.split(editor_cmd) + [str(tmp_path)], check=False)
        after = tmp_path.read_bytes()
        if after == before:
            console.print("[yellow]No changes detected.[/yellow]")
            return
        with _client(ctx) as client:
            client.upload(tmp_path, remote_path)
        console.print(f"[green]Updated remote file:[/green] {remote_path}")
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Snapshot / env
# ---------------------------------------------------------------------------


@main.group()
def snapshot():
    """VM snapshot helpers."""


@snapshot.command("save")
@click.argument("vm")
@click.argument("name")
@click.option(
    "--provider",
    default="proxmox",
    show_default=True,
    type=click.Choice(["proxmox", "virtualbox"]),
)
@click.option("--proxmox-host", default="", help="Run qm via SSH on this Proxmox host.")
@click.option("--proxmox-user", default="root", show_default=True)
@click.option(
    "--vmstate/--no-vmstate",
    default=False,
    show_default=True,
    help="Proxmox only: include VM state.",
)
def snapshot_save(vm, name, provider, proxmox_host, proxmox_user, vmstate):
    """Save VM snapshot."""
    if provider == "proxmox":
        cmd = ["qm", "snapshot", vm, name]
        if vmstate:
            cmd += ["--vmstate", "1"]
        result = _run_host_command(
            cmd,
            ssh_host=proxmox_host,
            ssh_user=proxmox_user,
        )
        if result.returncode != 0:
            raise click.ClickException(
                result.stderr.strip()
                or result.stdout.strip()
                or "proxmox snapshot save failed"
            )
        console.print(f"[green]Proxmox snapshot saved:[/green] vmid={vm} name={name}")
        return

    if provider == "virtualbox":
        result = subprocess.run(
            ["VBoxManage", "snapshot", vm, "take", name],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise click.ClickException(result.stderr.strip() or "snapshot save failed")
        console.print(f"[green]Snapshot saved:[/green] {vm}:{name}")


@snapshot.command("restore")
@click.argument("vm")
@click.argument("name")
@click.option(
    "--provider",
    default="proxmox",
    show_default=True,
    type=click.Choice(["proxmox", "virtualbox"]),
)
@click.option("--proxmox-host", default="", help="Run qm via SSH on this Proxmox host.")
@click.option("--proxmox-user", default="root", show_default=True)
@click.option(
    "--start/--no-start",
    default=False,
    show_default=True,
    help="Proxmox only: start VM after rollback.",
)
def snapshot_restore(
    vm,
    name,
    provider,
    proxmox_host,
    proxmox_user,
    start,
):
    """Restore VM snapshot."""
    if provider == "proxmox":
        cmd = ["qm", "rollback", vm, name]
        if start:
            cmd += ["--start", "1"]
        result = _run_host_command(
            cmd,
            ssh_host=proxmox_host,
            ssh_user=proxmox_user,
        )
        if result.returncode != 0:
            raise click.ClickException(
                result.stderr.strip()
                or result.stdout.strip()
                or "proxmox snapshot restore failed"
            )
        console.print(
            f"[green]Proxmox snapshot restored:[/green] vmid={vm} name={name}"
        )
        return

    if provider == "virtualbox":
        result = subprocess.run(
            ["VBoxManage", "snapshot", vm, "restore", name],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise click.ClickException(
                result.stderr.strip() or "snapshot restore failed"
            )
        console.print(f"[green]Snapshot restored:[/green] {vm}:{name}")


@main.group()
def env():
    """Environment variable helpers."""


@env.command("list")
@click.pass_context
def env_list(ctx):
    """List environment variables."""
    with _client(ctx) as client:
        result = client.exec("set", timeout=30)
    _ensure_success(result, "env list")
    for line in result.get("stdout", "").splitlines():
        if "=" in line:
            console.print(line, highlight=False)


@env.command("set")
@click.argument("name")
@click.argument("value")
@click.option("--persist/--no-persist", default=True, show_default=True)
@click.option("--timeout", default=30, type=int)
@click.pass_context
def env_set(ctx, name, value, persist, timeout):
    """Set an environment variable."""
    with _client(ctx) as client:
        if persist:
            result = client.exec(
                f"setx {_cmd_quote(name)} {_cmd_quote(value)}",
                timeout=timeout,
            )
        else:
            result = client.exec(
                f"set {_cmd_quote(name + '=' + value)} && echo Updated",
                timeout=timeout,
            )
    _print_exec_result(result, ctx)


# ---------------------------------------------------------------------------
# setup  (bundled installer management)
# ---------------------------------------------------------------------------

INSTALLERS_DIR = Path(__file__).resolve().parent.parent.parent / "installs"

_INSTALLERS = {
    "python": {
        "archive": "python-3.4.10.zip",
        "description": "Python 3.4.10 for Windows XP",
        "remote_dir": r"C:\Python34",
    },
    "ollydbg": {
        "archive": "ollydbg-1.10.zip",
        "description": "OllyDbg 1.10 debugger",
        "remote_dir": r"C:\OllyDbg",
    },
}


@main.group()
def setup():
    """Upload and install bundled tools on the XP machine."""


@setup.command("list")
def setup_list():
    """List available installers."""
    table = Table(title="Bundled Installers")
    table.add_column("Name", style="cyan")
    table.add_column("Archive", style="green")
    table.add_column("Description")
    table.add_column("Status")

    for name, info in sorted(_INSTALLERS.items()):
        archive_path = INSTALLERS_DIR / info["archive"]
        status = "available" if archive_path.is_file() else "[red]missing[/red]"
        table.add_row(name, info["archive"], info["description"], status)

    console.print(table)


@setup.command("install")
@click.argument("name", type=click.Choice(sorted(_INSTALLERS.keys())))
@click.option("--timeout", default=300, type=int, show_default=True)
@click.pass_context
def setup_install(ctx, name, timeout):
    """Upload and extract a bundled installer on the XP machine."""
    info = _INSTALLERS[name]
    archive_path = INSTALLERS_DIR / info["archive"]
    if not archive_path.is_file():
        raise click.ClickException(f"Installer archive not found: {archive_path}")

    remote_dir = info["remote_dir"]
    remote_zip = rf"C:\xpctl\tmp\{info['archive']}"

    with _client(ctx) as client:
        console.print(f"[cyan]Uploading {info['archive']}...[/cyan]")
        client.exec(r'if not exist "C:\xpctl\tmp" mkdir "C:\xpctl\tmp"')
        client.upload(archive_path, remote_zip)

        console.print(f"[cyan]Extracting to {remote_dir}...[/cyan]")
        extract_script = (
            "import zipfile, os\n"
            f"dst = r'{remote_dir}'\n"
            "if not os.path.isdir(dst):\n"
            "    os.makedirs(dst)\n"
            f"zipfile.ZipFile(r'{remote_zip}').extractall(dst)\n"
            f"os.remove(r'{remote_zip}')\n"
            f"result = {{'installed': True, 'path': dst}}\n"
        )
        data = _exec_python_json(client, extract_script, timeout=timeout)

    console.print(
        f"[green]Installed {info['description']} to {data.get('path', remote_dir)}[/green]"
    )


# ---------------------------------------------------------------------------
# agent  (lifecycle management)
# ---------------------------------------------------------------------------


@main.group()
def agent():
    """Agent lifecycle management."""


@agent.command()
@click.pass_context
def deploy(ctx):
    """Push the agent to XP via SCP."""
    p = ctx.ensure_object(dict)
    ssh = SSHTransport(p["host"], p["user"], p["password"])
    deployer = AgentDeployer(ssh)
    deployer.deploy()
    console.print("[green]Agent deployed successfully.[/green]")


@agent.command()
@click.pass_context
def start(ctx):
    """Start the agent on XP."""
    p = ctx.ensure_object(dict)
    ssh = SSHTransport(p["host"], p["user"], p["password"])
    deployer = AgentDeployer(ssh)
    deployer.start(p["port"])
    console.print(f"[green]Agent started on port {p['port']}.[/green]")


@agent.command()
@click.pass_context
def stop(ctx):
    """Stop the agent on XP."""
    p = ctx.ensure_object(dict)
    ssh = SSHTransport(p["host"], p["user"], p["password"])
    deployer = AgentDeployer(ssh)
    deployer.stop()
    console.print("[green]Agent stopped.[/green]")


@agent.command()
@click.pass_context
def status(ctx):
    """Check agent status."""
    p = ctx.ensure_object(dict)
    ssh = SSHTransport(p["host"], p["user"], p["password"])
    deployer = AgentDeployer(ssh)
    s = deployer.status(p["port"])

    if s["running"]:
        console.print(
            f"[green]Agent is running[/green] (v{s.get('version', '?')}, pid {s.get('pid', '?')})"
        )
        debuggers = s.get("debuggers", {})
        if debuggers:
            console.print(f"  Debuggers: {', '.join(debuggers.keys())}")
    else:
        err_console.print("[red]Agent is not running.[/red]")
        ctx.exit(1)


@agent.command()
@click.pass_context
def redeploy(ctx):
    """Stop, deploy, and restart the agent."""
    p = ctx.ensure_object(dict)
    ssh = SSHTransport(p["host"], p["user"], p["password"])
    deployer = AgentDeployer(ssh)
    deployer.redeploy(p["port"])
    console.print("[green]Agent redeployed and started.[/green]")


@agent.command()
@click.pass_context
def install(ctx):
    """Full install: deploy, start, and register for boot startup."""
    p = ctx.ensure_object(dict)
    ssh = SSHTransport(p["host"], p["user"], p["password"])
    deployer = AgentDeployer(ssh)
    deployer.install(p["port"])
    console.print("[green]Agent installed and registered for startup.[/green]")


@agent.command()
@click.pass_context
def uninstall(ctx):
    """Remove startup entry, stop agent, and clean up files."""
    p = ctx.ensure_object(dict)
    ssh = SSHTransport(p["host"], p["user"], p["password"])
    deployer = AgentDeployer(ssh)
    deployer.uninstall(p["port"])
    console.print("[green]Agent uninstalled.[/green]")


@agent.command("startup-status")
@click.pass_context
def startup_status(ctx):
    """Check if agent is registered in Windows startup."""
    with _client(ctx) as client:
        result = client.startup_status()

    if result.get("installed"):
        console.print(
            f"[green]Startup registered:[/green] {result.get('command', '?')}"
        )
    else:
        err_console.print("[yellow]No startup entry found.[/yellow]")


@agent.command()
@click.option(
    "--wait/--no-wait",
    default=True,
    show_default=True,
    help="Wait for agent to come back up after reboot.",
)
@click.option(
    "--timeout",
    default=180,
    type=int,
    show_default=True,
    help="Max seconds to wait for agent to come back.",
)
@click.pass_context
def reboot(ctx, wait, timeout):
    """Reboot the XP machine and optionally wait for reconnection."""
    with _client(ctx) as client:
        if not wait:
            try:
                client._request("reboot", {"delay": 0, "force": True})
            except (ConnectionError, BrokenPipeError, OSError):
                pass
            console.print("[green]Reboot initiated (not waiting).[/green]")
            return

        with console.status("[cyan]Rebooting and waiting for agent..."):
            ok = client.reboot(wait=True, timeout=float(timeout))

    if ok:
        console.print("[green]Machine rebooted. Agent is back up.[/green]")
    else:
        err_console.print(f"[red]Agent did not come back within {timeout}s.[/red]")
        ctx.exit(1)


if __name__ == "__main__":
    main()
