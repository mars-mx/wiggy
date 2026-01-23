"""Factory Droid engine definition."""

from wiggy.engines.base import Engine

DROID = Engine(
    name="Factory Droid",
    cli_command="droid",
    install_info="https://docs.factory.ai/cli/getting-started/quickstart",
)
