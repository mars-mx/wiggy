"""Configuration file loading and merging."""

import os
from pathlib import Path

import click
import yaml

from wiggy.config.schema import DEFAULT_CONFIG, WiggyConfig
from wiggy.console import console

CONFIG_FILENAME = "config.yaml"


def get_home_config_path() -> Path:
    """Get path to global config: ~/.wiggy/config.yaml."""
    return Path.home() / ".wiggy" / CONFIG_FILENAME


def get_local_config_path() -> Path:
    """Get path to local config: ./.wiggy/config.yaml."""
    return Path.cwd() / ".wiggy" / CONFIG_FILENAME


def home_config_exists() -> bool:
    """Check if the global home config exists."""
    return get_home_config_path().exists()


def local_config_exists() -> bool:
    """Check if the local project config exists."""
    return get_local_config_path().exists()


def load_yaml_config(path: Path) -> dict[str, object] | None:
    """Load a YAML config file, return None if not found or empty."""
    if not path.exists():
        return None
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
            if data is None:
                return None
            if not isinstance(data, dict):
                return None
            # yaml.safe_load returns Any, but we've verified it's a dict
            result: dict[str, object] = data
            return result
    except yaml.YAMLError:
        return None


def load_config() -> WiggyConfig:
    """Load merged configuration.

    Precedence (lowest to highest):
    1. Built-in defaults
    2. Global config (~/.wiggy/config.yaml)
    3. Local config (./.wiggy/config.yaml)

    Returns merged WiggyConfig.
    """
    # Start with defaults
    config = DEFAULT_CONFIG

    # Layer home config
    home_path = get_home_config_path()
    home_data = load_yaml_config(home_path)
    if home_data:
        home_config = WiggyConfig.from_dict(home_data)
        config = config.merge(home_config)

    # Layer local config
    local_path = get_local_config_path()
    local_data = load_yaml_config(local_path)
    if local_data:
        local_config = WiggyConfig.from_dict(local_data)
        config = config.merge(local_config)

    return config


def save_config(config: WiggyConfig, path: Path) -> None:
    """Save config to a YAML file.

    Creates parent directories if needed.
    Only saves non-None values.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = config.to_dict()
    with path.open("w") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def resolve_git_author(
    config: WiggyConfig,
) -> tuple[str | None, str | None]:
    """Resolve git author name and email for Docker containers.

    Precedence (highest to lowest):
    1. WIGGY_GIT_AUTHOR_NAME / WIGGY_GIT_AUTHOR_EMAIL env vars
    2. Config values (already merged: defaults < home < local)
    3. Interactive prompt (saves to global config for future runs)

    Returns (git_author_name, git_author_email).
    """
    name = os.environ.get("WIGGY_GIT_AUTHOR_NAME") or config.git_author_name
    email = os.environ.get("WIGGY_GIT_AUTHOR_EMAIL") or config.git_author_email

    if not name or not email:
        console.print(
            "\n[bold]Git author identity required for Docker commits.[/bold]"
        )
        if not name:
            name = click.prompt("Git author name")
        if not email:
            email = click.prompt("Git author email")
        # Save to global config for future runs
        save_cfg = WiggyConfig(git_author_name=name, git_author_email=email)
        home_path = get_home_config_path()
        existing = load_config()
        merged = existing.merge(save_cfg)
        save_config(merged, home_path)
        console.print(f"[dim]Saved git author to {home_path}[/dim]")

    return name, email
