"""Debugger-related CLI commands."""

from __future__ import annotations

import click
from rich.table import Table

from xpctl.debuggers import DEBUGGER_DESCRIPTIONS

from . import support


def register_debug_commands(main: click.Group) -> None:
    @main.group()
    def debug():
        """Debugger integration (OllyDbg, WinDbg/CDB, x64dbg)."""

    @debug.command("list")
    @click.pass_context
    def debug_list(ctx):
        """List debuggers installed on XP."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            installed = client.debug.list()

        if not installed:
            support.console.print("[yellow]No debuggers detected on XP.[/yellow]")
            return

        table = Table(title="Installed Debuggers")
        table.add_column("Name", style="cyan")
        table.add_column("Path", style="green")
        table.add_column("Description")

        for name, path in sorted(installed.items()):
            desc = DEBUGGER_DESCRIPTIONS.get(name, "")
            table.add_row(name, path, desc)

        support.console.print(table)

    @debug.command("ps")
    @click.option("--filter", "filter_str", default="")
    @click.pass_context
    def debug_ps(ctx, filter_str):
        """List debuggable processes on XP."""
        with support._client(ctx) as client:
            procs = client.processes(filter_str)

        table = Table(title="Processes")
        table.add_column("PID", style="cyan", justify="right")
        table.add_column("Name", style="green")
        table.add_column("Memory")

        for proc in procs:
            table.add_row(
                str(proc.get("pid", "?")),
                proc.get("name", "?"),
                proc.get("memory", ""),
            )

        support.console.print(table)

    @debug.group()
    def olly():
        """OllyDbg commands."""

    @olly.command("launch")
    @click.argument("exe_path")
    @click.pass_context
    def olly_launch(ctx, exe_path):
        """Launch OllyDbg with a target executable."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            sid = client.debug.olly.launch(exe_path)
        support.console.print(f"[green]Session started:[/green] {sid}")

    @olly.command("attach")
    @click.argument("pid", type=int)
    @click.pass_context
    def olly_attach(ctx, pid):
        """Attach OllyDbg to a running process."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            sid = client.debug.olly.attach(pid)
        support.console.print(f"[green]Attached:[/green] {sid}")

    @olly.command("run-script")
    @click.argument("script_path")
    @click.option("--session", "session_id", required=True, help="Session ID")
    @click.pass_context
    def olly_run_script(ctx, script_path, session_id):
        """Execute an OllyScript (.osc) file."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            output = client.debug.olly.run_script(session_id, script_path)
        support.console.print(output, highlight=False)

    @olly.command("log")
    @click.option("--session", "session_id", required=True, help="Session ID")
    @click.pass_context
    def olly_log(ctx, session_id):
        """Retrieve OllyDbg log output."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            output = client.debug.olly.log(session_id)
        support.console.print(output, highlight=False)

    @olly.command("detach")
    @click.option("--session", "session_id", required=True, help="Session ID")
    @click.pass_context
    def olly_detach(ctx, session_id):
        """Close an OllyDbg session."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            client.debug.olly.detach(session_id)
        support.console.print("[green]Session closed.[/green]")

    @debug.group()
    def windbg():
        """WinDbg / CDB commands."""

    @windbg.command("launch")
    @click.argument("exe_path")
    @click.pass_context
    def windbg_launch(ctx, exe_path):
        """Launch CDB (command-line WinDbg) with a target."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            sid = client.debug.windbg.launch(exe_path)
        support.console.print(f"[green]Session started:[/green] {sid}")

    @windbg.command("attach")
    @click.argument("pid", type=int)
    @click.pass_context
    def windbg_attach(ctx, pid):
        """Attach CDB to a running process."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            sid = client.debug.windbg.attach(pid)
        support.console.print(f"[green]Attached:[/green] {sid}")

    @windbg.command("cmd")
    @click.argument("command")
    @click.option("--session", "session_id", required=True, help="Session ID")
    @click.pass_context
    def windbg_cmd(ctx, command, session_id):
        """Send a debugger command to a CDB session."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            output = client.debug.windbg.cmd(session_id, command)
        support.console.print(output, highlight=False)

    @windbg.command("analyze")
    @click.argument("dump_path")
    @click.pass_context
    def windbg_analyze(ctx, dump_path):
        """Analyze a crash dump with CDB."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            sid = None
            try:
                sid = client.debug.windbg.launch(dump_path)
                output = client.debug.windbg.cmd(sid, "!analyze -v")
            finally:
                if sid is not None:
                    client.debug.windbg.detach(sid)
        support.console.print(output, highlight=False)

    @windbg.command("detach")
    @click.option("--session", "session_id", required=True, help="Session ID")
    @click.pass_context
    def windbg_detach(ctx, session_id):
        """Close a CDB session."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            client.debug.windbg.detach(session_id)
        support.console.print("[green]Session closed.[/green]")

    @debug.group()
    def x64dbg():
        """x32dbg / x64dbg commands."""

    @x64dbg.command("launch")
    @click.argument("exe_path")
    @click.pass_context
    def x64dbg_launch(ctx, exe_path):
        """Launch x32dbg with a target executable."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            sid = client.debug.x64dbg.launch(exe_path)
        support.console.print(f"[green]Session started:[/green] {sid}")

    @x64dbg.command("attach")
    @click.argument("pid", type=int)
    @click.pass_context
    def x64dbg_attach(ctx, pid):
        """Attach x32dbg to a running process."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            sid = client.debug.x64dbg.attach(pid)
        support.console.print(f"[green]Attached:[/green] {sid}")

    @x64dbg.command("cmd")
    @click.argument("command")
    @click.option("--session", "session_id", required=True, help="Session ID")
    @click.pass_context
    def x64dbg_cmd(ctx, command, session_id):
        """Send a command to an x32dbg session."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            output = client.debug.x64dbg.cmd(session_id, command)
        support.console.print(output, highlight=False)

    @x64dbg.command("run-script")
    @click.argument("script_path")
    @click.option("--session", "session_id", required=True, help="Session ID")
    @click.pass_context
    def x64dbg_run_script(ctx, script_path, session_id):
        """Execute an x64dbg script file."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            output = client.debug.x64dbg.run_script(session_id, script_path)
        support.console.print(output, highlight=False)

    @x64dbg.command("detach")
    @click.option("--session", "session_id", required=True, help="Session ID")
    @click.pass_context
    def x64dbg_detach(ctx, session_id):
        """Close an x32dbg session."""
        with support._client(ctx) as client:
            support._require_tcp_agent(client, "Debugger commands")
            client.debug.x64dbg.detach(session_id)
        support.console.print("[green]Session closed.[/green]")
