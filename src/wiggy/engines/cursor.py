"""Cursor engine definition."""

from wiggy.engines.base import Engine

CURSOR = Engine(
    name="Cursor",
    cli_command="agent",
    install_info="Cursor IDE installation",
)
