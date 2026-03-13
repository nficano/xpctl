"""Execution, scripting, and registry CLI commands."""

from __future__ import annotations

import time
from pathlib import Path

import click

from . import support


def register_exec_commands(main: click.Group) -> None:
    @main.command("exec")
    @click.argument("cmd", nargs=-1, required=True)
    @click.option("--timeout", default=30, type=int)
    @click.option("--python", "use_python", is_flag=True, help="Execute as Python code")
    @click.pass_context
    def exec_cmd(ctx, cmd, timeout, use_python):
        """Execute a remote command."""
        cmd_str = " ".join(cmd)
        with support._client(ctx) as client:
            if use_python:
                result = client.exec_python(cmd_str, timeout)
            else:
                result = client.exec(cmd_str, timeout)

        if result.get("stdout"):
            support.console.print(result["stdout"], end="", highlight=False)
        if result.get("stderr"):
            support.err_console.print(result["stderr"], end="", highlight=False)
        ctx.exit(result.get("returncode", 0))

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
        with support._client(ctx) as client:
            result = client.bat_run(path, args=list(args), timeout=timeout)

        if result.get("stdout"):
            support.console.print(result["stdout"], end="", highlight=False)
        if result.get("stderr"):
            support.err_console.print(result["stderr"], end="", highlight=False)
        ctx.exit(result.get("returncode", 0))

    @bat.command("push-run")
    @click.argument("local_path", type=click.Path(exists=True))
    @click.argument("args", nargs=-1)
    @click.option("--timeout", default=60, type=int)
    @click.pass_context
    def bat_push_run(ctx, local_path, args, timeout):
        """Upload and execute a local .bat file on XP."""
        with support._client(ctx) as client:
            result = client.bat_push_run(local_path, args=list(args), timeout=timeout)

        if result.get("stdout"):
            support.console.print(result["stdout"], end="", highlight=False)
        if result.get("stderr"):
            support.err_console.print(result["stderr"], end="", highlight=False)
        ctx.exit(result.get("returncode", 0))

    @bat.command("create")
    @click.argument("remote_path")
    @click.argument("commands", nargs=-1, required=True)
    @click.pass_context
    def bat_create(ctx, remote_path, commands):
        """Create a .bat file on XP from inline commands."""
        with support._client(ctx) as client:
            result = client.bat_create(remote_path, list(commands))
        support.console.print(f"[green]Created {result['path']}[/green]")

    @main.group()
    def reg():
        """Registry operations."""

    @reg.command("read")
    @click.argument("key")
    @click.option(
        "--value", "value_name", default="", help="Value name within the key."
    )
    @click.option("--timeout", default=30, type=int)
    @click.pass_context
    def reg_read(ctx, key, value_name, timeout):
        """Read a registry key/value."""
        cmd = f"reg query {support._cmd_quote(key)}"
        if value_name:
            cmd += f" /v {support._cmd_quote(value_name)}"
        with support._client(ctx) as client:
            result = client.exec(cmd, timeout=timeout)
        support._print_exec_result(result, ctx)

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
            f"reg add {support._cmd_quote(key)} /v {support._cmd_quote(name)} "
            f"/t {value_type} /d {support._cmd_quote(data)}"
        )
        if force:
            cmd += " /f"
        with support._client(ctx) as client:
            result = client.exec(cmd, timeout=timeout)
        support._print_exec_result(result, ctx)

    @reg.command("delete")
    @click.argument("key")
    @click.option(
        "--value", "value_name", default="", help="Delete only this value name."
    )
    @click.option("--force", is_flag=True, help="Skip confirmation.")
    @click.option("--timeout", default=30, type=int)
    @click.pass_context
    def reg_delete(ctx, key, value_name, force, timeout):
        """Delete a registry key or value."""
        if not force:
            target = f"{key}\\{value_name}" if value_name else key
            if not click.confirm(f"Delete registry entry {target}?"):
                return
        cmd = f"reg delete {support._cmd_quote(key)}"
        if value_name:
            cmd += f" /v {support._cmd_quote(value_name)}"
        cmd += " /f"
        with support._client(ctx) as client:
            result = client.exec(cmd, timeout=timeout)
        support._print_exec_result(result, ctx)

    @reg.command("export")
    @click.argument("key")
    @click.argument("local_path", type=click.Path())
    @click.option("--timeout", default=60, type=int)
    @click.pass_context
    def reg_export(ctx, key, local_path, timeout):
        """Export a registry key and pull the .reg file locally."""
        remote_tmp = rf"C:\xpctl\tmp\reg_export_{int(time.time() * 1000)}.reg"
        with support._client(ctx) as client:
            client.exec(
                r'if not exist "C:\xpctl\tmp" mkdir "C:\xpctl\tmp"', timeout=timeout
            )
            result = client.exec(
                f"reg export {support._cmd_quote(key)} {support._cmd_quote(remote_tmp)} /y",
                timeout=timeout,
            )
            support._ensure_success(result, "reg export")
            client.download(remote_tmp, local_path)
            try:
                client.rm(remote_tmp)
            except Exception:
                pass
        support.console.print(f"[green]Exported registry key to {local_path}[/green]")

    @main.command("script")
    @click.argument("script_path", type=click.Path(exists=True))
    @click.pass_context
    def script_run(ctx, script_path):
        """Run a local Python script with `client` injected."""
        source = Path(script_path).read_text()
        with support._client(ctx) as client:
            globs = {
                "__name__": "__main__",
                "__file__": script_path,
                "client": client,
                "console": support.console,
                "err_console": support.err_console,
            }
            exec(compile(source, script_path, "exec"), globs, globs)

    @main.command("shell")
    @click.option(
        "--session", "session_id", default="default", help="Shell session ID."
    )
    @click.pass_context
    def shell_cmd(ctx, session_id):
        """Interactive remote Python 3.4 shell on the XP machine."""
        try:
            import readline  # noqa: F401
        except ImportError:
            pass

        with support._client(ctx) as client:
            support._require_tcp_agent(client, "The interactive shell")
            info = client.agent_info()
            py_ver = info.get("python", "?")
            support.console.print(
                f"[green]Remote Python {py_ver} shell[/green] (session={session_id}). "
                "Ctrl-D to exit, %reset to clear namespace."
            )

            prompt1 = ">>> "
            prompt2 = "... "
            more = False

            while True:
                try:
                    line = input(prompt2 if more else prompt1)
                except EOFError:
                    support.console.print("\n[yellow]Disconnected.[/yellow]")
                    break
                except KeyboardInterrupt:
                    support.console.print("\nKeyboardInterrupt")
                    more = False
                    continue

                if not more and line.strip() == "%reset":
                    client.pyshell_reset(session_id)
                    support.console.print("[green]Namespace reset.[/green]")
                    continue

                result = client.pyshell_eval(line, session_id)
                stdout = result.get("stdout", "")
                stderr = result.get("stderr", "")
                more = result.get("more", False)

                if stdout:
                    support.console.print(stdout, end="", highlight=False)
                if stderr:
                    support.err_console.print(stderr, end="", highlight=False)

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
            with support._client(ctx) as client:
                while True:
                    runs += 1
                    support.console.print(f"[cyan][{runs}] {time.ctime()}[/cyan]")
                    result = client.exec(cmd_str, timeout=timeout)
                    support._print_exec_result(result)
                    if count and runs >= count:
                        break
                    time.sleep(interval)
        except KeyboardInterrupt:
            support.console.print("\n[yellow]Stopped.[/yellow]")
