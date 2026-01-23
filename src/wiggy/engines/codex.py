"""Codex engine definition."""

from wiggy.engines.base import Engine

CODEX = Engine(
    name="Codex",
    cli_command="codex",
    install_info="In PATH",
)
