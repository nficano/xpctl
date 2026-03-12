"""CLI entrypoint for xpctl."""

from __future__ import annotations

import click

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
def main(ctx, host, port, transport_mode, password, user, verify_host_key):
    """Xpctl — Remote management toolkit for Windows XP VM."""
    ctx.ensure_object(dict).update(
        host=host,
        port=port,
        transport_mode=transport_mode,
        password=password,
        user=user,
        verify_host_key=verify_host_key,
    )


register_admin_commands(main)
register_debug_commands(main)
register_exec_commands(main)
register_file_commands(main)
register_reverse_commands(main)
register_system_commands(main)


if __name__ == "__main__":
    main()
