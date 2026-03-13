"""File transfer and file-oriented CLI commands."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import click
from rich.table import Table

from xpctl.__about__ import __version__
from xpctl.resources import read_remote_script

from . import support


def register_file_commands(main: click.Group) -> None:
    @main.command()
    @click.argument("local_path", type=click.Path(exists=True))
    @click.argument("remote_path")
    @click.pass_context
    def upload(ctx, local_path, remote_path):
        """Upload a file to XP."""
        with support._client(ctx) as client:
            result = client.upload(local_path, remote_path)
        support.console.print(
            f"[green]Uploaded {result.get('bytes_written', '?')} bytes to {remote_path}[/green]"
        )

    @main.command("fetch-exe")
    @click.argument("url")
    @click.option("--name", help="Output filename on XP (defaults from URL).")
    @click.option(
        "--remote-dir",
        default="",
        help=r"Remote destination directory (default: C:\xpctl\downloads).",
    )
    @click.option("--timeout", default=120, type=int, show_default=True)
    @click.pass_context
    def fetch_exe(ctx, url, name, remote_dir, timeout):
        """Download an EXE URL locally and upload it to XP."""
        filename = name or support._exe_filename_from_url(url)
        destination_dir = remote_dir or support._default_remote_download_dir()
        destination_root = destination_dir.rstrip("\\/")
        destination = f"{destination_root}\\{filename}"

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="xpctl_", suffix=".exe", delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)

            support.console.print(f"[cyan]Downloading:[/cyan] {url}")
            req = Request(url, headers={"User-Agent": f"xpctl/{__version__}"})
            with urlopen(req, timeout=timeout) as resp, tmp_path.open("wb") as out:
                shutil.copyfileobj(resp, out)

            size = tmp_path.stat().st_size
            if size == 0:
                raise click.ClickException("Downloaded file is empty.")

            with support._client(ctx) as client:
                client.exec(
                    f'if not exist "{destination_dir}" mkdir "{destination_dir}"'
                )
                result = client.upload(tmp_path, destination)

            support.console.print(
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
        with support._client(ctx) as client:
            result = client.download(remote_path, local_path)
        support.console.print(
            f"[green]Downloaded {result['size']} bytes to {result['path']}[/green]"
        )

    @main.command()
    @click.argument("path", default=".")
    @click.option("-r", "--recursive", is_flag=True)
    @click.pass_context
    def ls(ctx, path, recursive):
        """List a remote directory."""
        with support._client(ctx) as client:
            entries = client.ls(path, recursive)

        table = Table(title=f"Directory: {path}")
        table.add_column("Type", style="cyan", width=4)
        table.add_column("Size", justify="right", style="green")
        table.add_column("Name")

        for entry in entries:
            entry_type = "DIR" if entry.get("type") == "dir" else "FILE"
            size = str(entry.get("size", "")) if entry.get("type") != "dir" else ""
            table.add_row(entry_type, size, entry.get("name", ""))

        support.console.print(table)

    @main.command()
    @click.argument("path")
    @click.option("-r", "--recursive", is_flag=True)
    @click.pass_context
    def rm(ctx, path, recursive):
        """Delete a remote file or directory."""
        with support._client(ctx) as client:
            client.rm(path, recursive)
        support.console.print(f"[green]Deleted: {path}[/green]")

    @main.command("push-run")
    @click.argument("script", type=click.Path(exists=True))
    @click.option("--timeout", default=60, type=int)
    @click.pass_context
    def push_run(ctx, script, timeout):
        """Upload and execute a script (.py or .bat) on XP."""
        with support._client(ctx) as client:
            result = client.push_and_run(script, timeout=timeout)

        if result.get("stdout"):
            support.console.print(result["stdout"], end="", highlight=False)
        if result.get("stderr"):
            support.err_console.print(result["stderr"], end="", highlight=False)
        ctx.exit(result.get("returncode", 0))

    @main.command("cat")
    @click.argument("remote_path")
    @click.option("--timeout", default=30, type=int)
    @click.pass_context
    def cat_cmd(ctx, remote_path, timeout):
        """Print a remote file."""
        with support._client(ctx) as client:
            result = client.exec(
                f"type {support._cmd_quote(remote_path)}", timeout=timeout
            )
        support._print_exec_result(result, ctx)

    @main.command("head")
    @click.argument("remote_path")
    @click.option("-n", "--lines", default=20, type=int, show_default=True)
    @click.option("--timeout", default=30, type=int)
    @click.pass_context
    def head_cmd(ctx, remote_path, lines, timeout):
        """Print first N lines from a remote file."""
        script = read_remote_script("head")
        with support._client(ctx) as client:
            data = support._exec_python_json(
                client,
                script,
                payload={"path": remote_path, "lines": lines},
                timeout=timeout,
            )
        support.console.print(data.get("text", ""), highlight=False)

    @main.command("tail")
    @click.argument("remote_path")
    @click.option("-n", "--lines", default=20, type=int, show_default=True)
    @click.option("--timeout", default=30, type=int)
    @click.pass_context
    def tail_cmd(ctx, remote_path, lines, timeout):
        """Print last N lines from a remote file."""
        script = read_remote_script("tail")
        with support._client(ctx) as client:
            data = support._exec_python_json(
                client,
                script,
                payload={"path": remote_path, "lines": lines},
                timeout=timeout,
            )
        support.console.print(data.get("text", ""), highlight=False)

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
        with support._client(ctx) as client:
            data = support._exec_python_json(
                client,
                script,
                payload={
                    "root": remote_path,
                    "glob": glob_pattern,
                    "regex": regex_pattern,
                },
                timeout=timeout,
            )
        for match in data.get("matches", []):
            support.console.print(match, highlight=False)

    @main.command("checksum")
    @click.argument("remote_path")
    @click.option("--algo", default="md5", type=click.Choice(["md5", "sha1", "sha256"]))
    @click.option("--timeout", default=30, type=int)
    @click.pass_context
    def checksum_cmd(ctx, remote_path, algo, timeout):
        """Calculate remote file checksum."""
        script = read_remote_script("checksum")
        with support._client(ctx) as client:
            data = support._exec_python_json(
                client,
                script,
                payload={"path": remote_path, "algo": algo},
                timeout=timeout,
            )
        support.console.print(f"{data['algo']} {data['hexdigest']}  {remote_path}")

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
            with support._client(ctx) as client:
                client.download(remote_path, tmp_path)
                before = tmp_path.read_bytes()
                subprocess.run([*shlex.split(editor_cmd), str(tmp_path)], check=False)
                after = tmp_path.read_bytes()
                if after == before:
                    support.console.print("[yellow]No changes detected.[/yellow]")
                    return
                client.upload(tmp_path, remote_path)
            support.console.print(f"[green]Updated remote file:[/green] {remote_path}")
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass
