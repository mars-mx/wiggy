"""OpenCode engine definition."""

from wiggy.engines.base import Engine

OPENCODE = Engine(
    name="OpenCode",
    cli_command="opencode",
    install_info="https://opencode.ai/docs/",
)
