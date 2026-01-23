"""Base engine definition."""

import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class Engine:
    """Definition of an AI coding engine."""

    name: str
    cli_command: str
    install_info: str
    docker_image: str | None = None
    credential_dir: str | None = None  # Path to credentials (e.g., "~/.claude")

    def is_installed(self) -> bool:
        """Check if this engine's CLI command is available in PATH."""
        return shutil.which(self.cli_command) is not None
