"""Administrative and lifecycle CLI commands."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import click
from rich.table import Table

from xpctl.deploy import AgentDeployer
from xpctl.transport.ssh import SSHTransport

from . import support


def _discover_installers_dir() -> Path:
    """Resolve the directory holding bundled installer archives."""
    if override := os.environ.get("XPCTL_INSTALLERS_DIR"):
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[3] / "installs"


INSTALLERS_DIR = _discover_installers_dir()

INSTALLERS = {
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
    "x64dbg": {
        "archive": "x64dbg-2025.08.19.zip",
        "description": "x64dbg snapshot debugger",
        "remote_dir": r"C:\x64dbg",
    },
}


def _agent_deployer(ctx: click.Context) -> AgentDeployer:
    """Build an agent deployer from the root CLI context."""
    params = ctx.ensure_object(dict)
    ssh = SSHTransport(
        params["host"],
        params["user"],
        params["password"],
        verify_host_key=params["verify_host_key"],
    )
    return AgentDeployer(ssh=ssh)


def register_admin_commands(main: click.Group) -> None:
    @main.command()
    @click.pass_context
    def ping(ctx):
        """Check if the agent is alive."""
        client = support._client(ctx)
        try:
            client.connect()
            ok = client.ping()
        except Exception:
            ok = False
        finally:
            client.disconnect()

        if ok:
            support.console.print("[green]Agent is alive[/green]")
        else:
            support.err_console.print("[red]Agent is unreachable[/red]")
            ctx.exit(1)

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
    @click.option(
        "--proxmox-host", default="", help="Run qm via SSH on this Proxmox host."
    )
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
            result = support._run_host_command(
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
            support.console.print(
                f"[green]Proxmox snapshot saved:[/green] vmid={vm} name={name}"
            )
            return

        result = subprocess.run(
            ["VBoxManage", "snapshot", vm, "take", name],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise click.ClickException(result.stderr.strip() or "snapshot save failed")
        support.console.print(f"[green]Snapshot saved:[/green] {vm}:{name}")

    @snapshot.command("restore")
    @click.argument("vm")
    @click.argument("name")
    @click.option(
        "--provider",
        default="proxmox",
        show_default=True,
        type=click.Choice(["proxmox", "virtualbox"]),
    )
    @click.option(
        "--proxmox-host", default="", help="Run qm via SSH on this Proxmox host."
    )
    @click.option("--proxmox-user", default="root", show_default=True)
    @click.option(
        "--start/--no-start",
        default=False,
        show_default=True,
        help="Proxmox only: start VM after rollback.",
    )
    def snapshot_restore(vm, name, provider, proxmox_host, proxmox_user, start):
        """Restore VM snapshot."""
        if provider == "proxmox":
            cmd = ["qm", "rollback", vm, name]
            if start:
                cmd += ["--start", "1"]
            result = support._run_host_command(
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
            support.console.print(
                f"[green]Proxmox snapshot restored:[/green] vmid={vm} name={name}"
            )
            return

        result = subprocess.run(
            ["VBoxManage", "snapshot", vm, "restore", name],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise click.ClickException(
                result.stderr.strip() or "snapshot restore failed"
            )
        support.console.print(f"[green]Snapshot restored:[/green] {vm}:{name}")

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

        for name, info in sorted(INSTALLERS.items()):
            archive_path = INSTALLERS_DIR / info["archive"]
            status = "available" if archive_path.is_file() else "[red]missing[/red]"
            table.add_row(name, info["archive"], info["description"], status)

        support.console.print(table)

    @setup.command("install")
    @click.argument("name", type=click.Choice(sorted(INSTALLERS.keys())))
    @click.option("--timeout", default=300, type=int, show_default=True)
    @click.pass_context
    def setup_install(ctx, name, timeout):
        """Upload and extract a bundled installer on the XP machine."""
        info = INSTALLERS[name]
        archive_path = INSTALLERS_DIR / info["archive"]
        if not archive_path.is_file():
            raise click.ClickException(f"Installer archive not found: {archive_path}")

        remote_dir = info["remote_dir"]
        remote_zip = rf"C:\xpctl\tmp\{info['archive']}"

        with support._client(ctx) as client:
            support.console.print(f"[cyan]Uploading {info['archive']}...[/cyan]")
            client.exec(r'if not exist "C:\xpctl\tmp" mkdir "C:\xpctl\tmp"')
            client.upload(archive_path, remote_zip)

            support.console.print(f"[cyan]Extracting to {remote_dir}...[/cyan]")
            from xpctl.templates import render

            extract_script = render(
                "extract_installer.py.j2",
                remote_dir=remote_dir,
                remote_zip=remote_zip,
            )
            data = support._exec_python_json(client, extract_script, timeout=timeout)

        support.console.print(
            f"[green]Installed {info['description']} to {data.get('path', remote_dir)}[/green]"
        )

    @main.group()
    def agent():
        """Agent lifecycle management."""

    @agent.command()
    @click.pass_context
    def deploy(ctx):
        """Push the agent to XP via SCP."""
        deployer = _agent_deployer(ctx)
        deployer.deploy()
        support.console.print("[green]Agent deployed successfully.[/green]")

    @agent.command()
    @click.pass_context
    def start(ctx):
        """Start the agent on XP."""
        params = ctx.ensure_object(dict)
        deployer = _agent_deployer(ctx)
        deployer.start(params["port"])
        support.console.print(f"[green]Agent started on port {params['port']}.[/green]")

    @agent.command()
    @click.pass_context
    def stop(ctx):
        """Stop the agent on XP."""
        params = ctx.ensure_object(dict)
        deployer = _agent_deployer(ctx)
        deployer.stop(params["port"])
        support.console.print("[green]Agent stopped.[/green]")

    @agent.command()
    @click.pass_context
    def status(ctx):
        """Check agent status."""
        params = ctx.ensure_object(dict)
        deployer = _agent_deployer(ctx)
        status_result = deployer.status(params["port"])

        if status_result["running"]:
            support.console.print(
                f"[green]Agent is running[/green] (v{status_result.get('version', '?')}, pid {status_result.get('pid', '?')})"
            )
            debuggers = status_result.get("debuggers", {})
            if debuggers:
                support.console.print(f"  Debuggers: {', '.join(debuggers.keys())}")
        else:
            support.err_console.print("[red]Agent is not running.[/red]")
            ctx.exit(1)

    @agent.command()
    @click.pass_context
    def redeploy(ctx):
        """Stop, deploy, and restart the agent."""
        params = ctx.ensure_object(dict)
        deployer = _agent_deployer(ctx)
        deployer.redeploy(params["port"])
        support.console.print("[green]Agent redeployed and started.[/green]")

    @agent.command()
    @click.pass_context
    def install(ctx):
        """Full install: deploy, start, and register for boot startup."""
        params = ctx.ensure_object(dict)
        deployer = _agent_deployer(ctx)
        deployer.install(params["port"])
        support.console.print(
            "[green]Agent installed and registered for startup.[/green]"
        )

    @agent.command()
    @click.pass_context
    def uninstall(ctx):
        """Remove startup entry, stop agent, and clean up files."""
        params = ctx.ensure_object(dict)
        deployer = _agent_deployer(ctx)
        deployer.uninstall(params["port"])
        support.console.print("[green]Agent uninstalled.[/green]")

    @agent.command("startup-status")
    @click.pass_context
    def startup_status(ctx):
        """Check if agent is registered in Windows startup."""
        with support._client(ctx) as client:
            result = client.startup_status()

        if result.get("installed"):
            support.console.print(
                f"[green]Startup registered:[/green] {result.get('command', '?')}"
            )
        else:
            support.err_console.print("[yellow]No startup entry found.[/yellow]")

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
        with support._client(ctx) as client:
            if not wait:
                try:
                    client._request("reboot", {"delay": 0, "force": True})
                except (ConnectionError, BrokenPipeError, OSError):
                    pass
                support.console.print("[green]Reboot initiated (not waiting).[/green]")
                return

            with support.console.status("[cyan]Rebooting and waiting for agent..."):
                ok = client.reboot(wait=True, timeout=float(timeout))

        if ok:
            support.console.print("[green]Machine rebooted. Agent is back up.[/green]")
        else:
            support.err_console.print(
                f"[red]Agent did not come back within {timeout}s.[/red]"
            )
            ctx.exit(1)
