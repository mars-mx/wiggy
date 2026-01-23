"""Output parsers for engine output."""

from wiggy.parsers.base import Parser
from wiggy.parsers.claude import ClaudeParser
from wiggy.parsers.messages import MessageType, ParsedMessage, SessionSummary
from wiggy.parsers.raw import RawParser

__all__ = [
    "Parser",
    "ClaudeParser",
    "RawParser",
    "ParsedMessage",
    "MessageType",
    "SessionSummary",
    "PARSERS",
    "get_parser_for_engine",
]

# Parser registry: engine name -> parser class
PARSERS: dict[str, type[Parser]] = {
    "claude": ClaudeParser,
    "raw": RawParser,
}


def get_parser_for_engine(engine_name: str) -> Parser:
    """Get parser instance for an engine.

    Args:
        engine_name: Name of the engine (e.g., "Claude Code").

    Returns:
        Parser instance. Falls back to RawParser for unknown engines.
    """
    # Normalize engine name for lookup
    normalized = engine_name.lower().replace(" ", "").replace("-", "")

    # Check for known engines
    if "claude" in normalized:
        return ClaudeParser()

    # Default to raw parser
    return RawParser()
