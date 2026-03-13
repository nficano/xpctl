"""System, networking, services, and environment CLI commands."""

from __future__ import annotations

import subprocess

import click
from rich.table import Table

from . import support


def register_system_commands(main: click.Group) -> None:
    @main.command()
    @click.pass_context
    def sysinfo(ctx):
        """Show XP system information."""
        with support._client(ctx) as client:
            info = client.sysinfo()

        table = Table(title="System Information")
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="green")

        for key, value in sorted(info.items()):
            table.add_row(key, str(value))

        support.console.print(table)

    @main.command()
    @click.option("--filter", "filter_str", default="")
    @click.pass_context
    def ps(ctx, filter_str):
        """List processes on XP."""
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

    @main.group()
    def net():
        """Network utilities."""

    @net.command("netstat")
    @click.option("--timeout", default=30, type=int)
    @click.pass_context
    def net_netstat(ctx, timeout):
        """Show netstat with PID mapping."""
        with support._client(ctx) as client:
            result = client.exec("netstat -ano", timeout=timeout)
        support._ensure_success(result, "netstat")

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
        support.console.print(table)

    @net.command("portfwd")
    @click.argument("local_port", type=int)
    @click.argument("remote_host")
    @click.argument("remote_port", type=int)
    @click.option("--background/--foreground", default=True, show_default=True)
    @click.pass_context
    def net_portfwd(ctx, local_port, remote_host, remote_port, background):
        """Create an SSH local port-forward tunnel."""
        params = ctx.ensure_object(dict)
        if params["password"]:
            raise click.ClickException(
                "`net portfwd` does not support --password. Use SSH keys or run ssh manually."
            )
        target = (
            f"{params['user']}@{params['host']}" if params["user"] else params["host"]
        )
        cmd = [
            "ssh",
            "-N",
            "-L",
            f"{local_port}:{remote_host}:{remote_port}",
            # Intentionally skip host key verification for ad-hoc tunnels into
            # ephemeral XP targets where usability outweighs TOFU prompts.
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            target,
        ]
        if background:
            proc = subprocess.Popen(cmd)
            support.console.print(
                f"[green]Port forward started:[/green] localhost:{local_port} -> {remote_host}:{remote_port} (pid {proc.pid})"
            )
        else:
            subprocess.run(cmd, check=False)

    @main.group()
    def svc():
        """Service control helpers."""

    @svc.command("list")
    @click.pass_context
    def svc_list(ctx):
        """List running services."""
        with support._client(ctx) as client:
            result = client.services("list")
        for name in result.get("services", []):
            support.console.print(name, highlight=False)

    @svc.command("start")
    @click.argument("name")
    @click.pass_context
    def svc_start(ctx, name):
        """Start a service."""
        with support._client(ctx) as client:
            result = client.services("start", name)
        support._print_exec_result(result, ctx)

    @svc.command("stop")
    @click.argument("name")
    @click.pass_context
    def svc_stop(ctx, name):
        """Stop a service."""
        with support._client(ctx) as client:
            result = client.services("stop", name)
        support._print_exec_result(result, ctx)

    @svc.command("status")
    @click.argument("name")
    @click.pass_context
    def svc_status(ctx, name):
        """Show service status."""
        with support._client(ctx) as client:
            result = client.services("status", name)
        support._print_exec_result(result, ctx)

    @main.group()
    def env():
        """Environment variable helpers."""

    @env.command("list")
    @click.pass_context
    def env_list(ctx):
        """List environment variables."""
        with support._client(ctx) as client:
            result = client.exec("set", timeout=30)
        support._ensure_success(result, "env list")
        for line in result.get("stdout", "").splitlines():
            if "=" in line:
                support.console.print(line, highlight=False)

    @env.command("set")
    @click.argument("name")
    @click.argument("value")
    @click.option("--persist/--no-persist", default=True, show_default=True)
    @click.option("--timeout", default=30, type=int)
    @click.pass_context
    def env_set(ctx, name, value, persist, timeout):
        """Set an environment variable."""
        if not persist:
            raise click.ClickException(
                "`env set --no-persist` is not supported because xpctl runs commands in isolated processes. Use --persist."
            )
        with support._client(ctx) as client:
            result = client.exec(
                f"setx {support._cmd_quote(name)} {support._cmd_quote(value)}",
                timeout=timeout,
            )
        support._print_exec_result(result, ctx)
