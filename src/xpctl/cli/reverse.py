"""Reverse-engineering and GUI CLI commands."""

from __future__ import annotations

import csv

import click
from rich.table import Table

from xpctl.resources import read_remote_script

from . import support


def register_reverse_commands(main: click.Group) -> None:
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
        with support._client(ctx) as client:
            result = client.exec(cmd, timeout=timeout)
        support._ensure_success(result, "dll list")
        table = Table(title=f"Loaded DLLs for PID {pid}")
        table.add_column("Process", style="cyan")
        table.add_column("PID", style="green")
        table.add_column("Modules")
        lines = [
            entry for entry in result.get("stdout", "").splitlines() if entry.strip()
        ]
        for line in lines:
            row = next(csv.reader([line]), [])
            if len(row) >= 3:
                table.add_row(row[0], row[1], row[2])
        support.console.print(table)

    @dll.command("inject")
    @click.argument("pid", type=int)
    @click.argument("dll_path")
    @click.option("--timeout", default=60, type=int)
    @click.pass_context
    def dll_inject(ctx, pid, dll_path, timeout):
        """Inject a DLL via CreateRemoteThread + LoadLibraryA."""
        script = read_remote_script("dll_inject")
        with support._client(ctx) as client:
            data = support._exec_python_json(
                client,
                script,
                payload={"pid": pid, "dll_path": dll_path},
                timeout=timeout,
            )
        support.console.print(f"[green]Injected:[/green] {data}")

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
        cmd = f"regsvr32 /s {mode}{support._cmd_quote(dll_path)}"
        with support._client(ctx) as client:
            result = client.exec(cmd, timeout=timeout)
        support._print_exec_result(result, ctx)

    @main.group()
    def com():
        """COM registration helpers."""

    @com.command("list")
    @click.option(
        "--filter", "filter_str", default="", help="Filter string for reg query."
    )
    @click.option("--timeout", default=60, type=int)
    @click.pass_context
    def com_list(ctx, filter_str, timeout):
        """List COM CLSID registrations."""
        cmd = r"reg query HKCR\CLSID /s"
        if filter_str:
            cmd += f" /f {support._cmd_quote(filter_str)}"
        with support._client(ctx) as client:
            result = client.exec(cmd, timeout=timeout)
        support._print_exec_result(result, ctx)

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
        remote_dump = remote_path or rf"C:\xpctl\tmp\mem_{pid}.dmp"
        script = read_remote_script("memdump")
        with support._client(ctx) as client:
            data = support._exec_python_json(
                client,
                script,
                payload={"pid": pid, "dump_path": remote_dump},
                timeout=timeout,
            )
            client.download(remote_dump, local_path)
        support.console.print(
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
        with support._client(ctx) as client:
            data = support._exec_python_json(
                client,
                script,
                payload={"pid": pid, "address": address, "size": size},
                timeout=timeout,
            )
        support.console.print(data["hex"])

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
        with support._client(ctx) as client:
            support._exec_python_json(
                client, script, payload={"path": remote_path}, timeout=timeout
            )
            client.download(remote_path, local_path)
        support.console.print(f"[green]Screenshot saved:[/green] {local_path}")

    @gui.command("window-list")
    @click.option("--timeout", default=30, type=int)
    @click.pass_context
    def gui_window_list(ctx, timeout):
        """List top-level windows."""
        script = read_remote_script("gui_window_list")
        with support._client(ctx) as client:
            data = support._exec_python_json(client, script, timeout=timeout)

        table = Table(title="Top-Level Windows")
        table.add_column("HWND", style="cyan")
        table.add_column("Class", style="green")
        table.add_column("Title")
        for window in data.get("windows", []):
            table.add_row(
                hex(int(window["hwnd"])),
                window.get("class", ""),
                window.get("title", ""),
            )
        support.console.print(table)

    @gui.command("sendkeys")
    @click.argument("keys")
    @click.option("--title", default="", help="Focus this exact window title first.")
    @click.option("--timeout", default=30, type=int)
    @click.pass_context
    def gui_sendkeys(ctx, keys, title, timeout):
        """Send keyboard input (ASCII-focused helper)."""
        script = read_remote_script("gui_sendkeys")
        with support._client(ctx) as client:
            data = support._exec_python_json(
                client,
                script,
                payload={"keys": keys, "title": title},
                timeout=timeout,
            )
        support.console.print(f"[green]Sent keys:[/green] {data['sent']}")
