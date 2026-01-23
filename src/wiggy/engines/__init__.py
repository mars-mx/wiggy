"""AI coding engine definitions and detection."""

from wiggy.engines.base import Engine
from wiggy.engines.claude import CLAUDE
from wiggy.engines.codex import CODEX
from wiggy.engines.copilot import COPILOT
from wiggy.engines.cursor import CURSOR
from wiggy.engines.droid import DROID
from wiggy.engines.opencode import OPENCODE
from wiggy.engines.qwen import QWEN

__all__ = [
    "Engine",
    "ENGINES",
    "CLAUDE",
    "CODEX",
    "COPILOT",
    "CURSOR",
    "DROID",
    "OPENCODE",
    "QWEN",
    "get_available_engines",
    "get_engine_by_name",
    "get_missing_engines",
]

ENGINES: tuple[Engine, ...] = (
    CLAUDE,
    OPENCODE,
    CURSOR,
    CODEX,
    QWEN,
    DROID,
    COPILOT,
)


def get_available_engines() -> list[Engine]:
    """Return list of engines that are currently installed."""
    return [engine for engine in ENGINES if engine.is_installed()]


def get_missing_engines() -> list[Engine]:
    """Return list of engines that are not installed."""
    return [engine for engine in ENGINES if not engine.is_installed()]


def get_engine_by_name(name: str) -> Engine | None:
    """Find engine by name (case-insensitive) or cli_command."""
    name_lower = name.lower()
    for engine in ENGINES:
        if engine.name.lower() == name_lower or engine.cli_command == name:
            return engine
    return None
