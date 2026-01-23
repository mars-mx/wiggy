"""Claude Code engine definition."""

from wiggy.engines.base import Engine

CLAUDE = Engine(
    name="Claude Code",
    cli_command="claude",
    install_info="https://github.com/anthropics/claude-code",
    docker_image="ghcr.io/mars-mx/wiggy-claude:latest",
    credential_dir="~/.claude",
    default_args=(
        "--dangerously-skip-permissions",
        "--print",
        "--output-format",
        "stream-json",
    ),
)
