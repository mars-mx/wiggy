"""Configuration and preflight checks."""

from wiggy.config.loader import (
    home_config_exists,
    load_config,
    local_config_exists,
    save_config,
)
from wiggy.config.schema import WiggyConfig

__all__ = [
    "WiggyConfig",
    "home_config_exists",
    "load_config",
    "local_config_exists",
    "save_config",
]
