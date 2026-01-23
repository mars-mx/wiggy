"""GitHub Copilot engine definition."""

from wiggy.engines.base import Engine

COPILOT = Engine(
    name="GitHub Copilot",
    cli_command="copilot",
    install_info="npm install -g @github/copilot",
)
