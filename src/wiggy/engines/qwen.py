"""Qwen-Code engine definition."""

from wiggy.engines.base import Engine

QWEN = Engine(
    name="Qwen-Code",
    cli_command="qwen",
    install_info="In PATH",
)
