"""Jinja2 template helpers for generating deployment scripts."""

from __future__ import annotations

from jinja2 import Environment, PackageLoader, select_autoescape

__all__ = ["render"]

_env = Environment(
    loader=PackageLoader("xpctl", "templates"),
    autoescape=select_autoescape([]),
    keep_trailing_newline=True,
)


def render(template_name: str, **kwargs: object) -> str:
    """Render a Jinja2 template by name with the given context variables.

    Args:
        template_name: Name of the template file (e.g. ``start_agent.bat.j2``).
        **kwargs: Context variables passed to the template.

    Returns:
        The rendered template string.
    """
    return _env.get_template(template_name).render(**kwargs)
