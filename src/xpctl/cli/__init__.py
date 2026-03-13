"""CLI entrypoint for xpctl."""

from __future__ import annotations

from typing import cast

import click
from click.core import ParameterSource

from xpctl.client import XPClient
from xpctl.config import DEFAULT_PROFILE, load_profile, save_profile
from xpctl.transport.factory import TransportMode

from . import support
from .admin import register_admin_commands
from .debug import register_debug_commands
from .exec import register_exec_commands
from .files import register_file_commands
from .reverse import register_reverse_commands
from .support import common_options
from .system import register_system_commands


@click.group()
@common_options
@click.pass_context
def main(ctx, profile, host, port, transport_mode, password, user, verify_host_key):
    """Xpctl — Remote management toolkit for Windows XP VM."""
    use_profile_defaults = (
        ctx.get_parameter_source("profile") is not ParameterSource.DEFAULT
    )
    resolved = support._resolve_connection_settings(
        profile_name=profile,
        host=host,
        port=port,
        transport_mode=transport_mode,
        user=user,
        password=password,
        use_profile_defaults=use_profile_defaults,
    )
    resolved["verify_host_key"] = verify_host_key
    ctx.ensure_object(dict).update(resolved)
    if (
        ctx.invoked_subcommand
        and ctx.invoked_subcommand != "configure"
        and not resolved["host"]
    ):
        raise click.UsageError(
            "Missing host. Provide --host, set XPCTL_HOST, or run `xpctl configure`."
        )


def _attempt_profile_connection(values: dict[str, str]) -> None:
    client = XPClient(
        host=values["hostname"],
        port=int(values["port"]),
        transport=cast(TransportMode, values["transport"]),
        user=values["username"],
        password=values["password"],
    )
    try:
        client.connect()
        if not client.ping():
            raise ConnectionError("Connection opened but ping failed")
    finally:
        client.disconnect()


@main.command()
@click.option(
    "--profile",
    "configure_profile",
    default=None,
    help="Profile name to configure.",
)
@click.pass_context
def configure(ctx: click.Context, configure_profile: str | None) -> None:
    """Interactively configure a saved connection profile."""
    profile_name = configure_profile or ctx.ensure_object(dict).get(
        "profile", DEFAULT_PROFILE
    )
    saved = load_profile(profile_name)
    values = {
        "hostname": saved.get("hostname", ""),
        "port": saved.get("port", support.CONFIGURE_DEFAULT_PORT)
        or support.CONFIGURE_DEFAULT_PORT,
        "transport": (
            saved.get("transport", support.CONFIGURE_DEFAULT_TRANSPORT)
            or support.CONFIGURE_DEFAULT_TRANSPORT
        ),
        "username": saved.get("username", ""),
        "password": saved.get("password", ""),
    }

    while True:
        values["hostname"] = support._prompt_string(
            "Hostname or IP", values["hostname"]
        )
        values["port"] = support._prompt_port(values["port"])
        values["username"] = support._prompt_string("Username", values["username"])
        values["password"] = support._prompt_string(
            "Password", values["password"], secret=True
        )
        values["transport"] = support._prompt_transport(values["transport"])

        try:
            _attempt_profile_connection(values)
        except Exception as exc:
            support.err_console.print(f"[red]Connection failed:[/red] {exc}")
            continue

        path = save_profile(profile_name, values)
        support.console.print(
            f"[green]Connection successful.[/green] Saved profile '{profile_name}' to {path}"
        )
        return


register_admin_commands(main)
register_debug_commands(main)
register_exec_commands(main)
register_file_commands(main)
register_reverse_commands(main)
register_system_commands(main)
