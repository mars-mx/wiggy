"""Initialization logic for wiggy directory structure."""

from pathlib import Path


def ensure_wiggy_dir() -> None:
    """Create .wiggy directory structure in current working directory.

    Creates:
        .wiggy/
        .wiggy/logs/
        .wiggy/.gitignore (with logs/ ignored)
    """
    wiggy_dir = Path.cwd() / ".wiggy"
    logs_dir = wiggy_dir / "logs"
    gitignore_path = wiggy_dir / ".gitignore"

    # Create directories (parents=True creates .wiggy if needed)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Create .gitignore if it doesn't exist
    if not gitignore_path.exists():
        gitignore_path.write_text("logs/\n")


def ensure_home_wiggy_dir() -> Path:
    """Create ~/.wiggy directory if it doesn't exist.

    Returns the path to the home wiggy directory.
    """
    home_wiggy = Path.home() / ".wiggy"
    home_wiggy.mkdir(parents=True, exist_ok=True)
    return home_wiggy
