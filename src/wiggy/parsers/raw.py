"""Raw output parser (no transformation)."""

from wiggy.parsers.base import Parser
from wiggy.parsers.messages import MessageType, ParsedMessage, SessionSummary


class RawParser(Parser):
    """Parser that passes through raw output unchanged."""

    name = "raw"

    def parse_line(self, line: str) -> ParsedMessage:
        """Return line as raw message."""
        return ParsedMessage(
            message_type=MessageType.RAW,
            content=line,
            raw=line,
        )

    def get_summary(self) -> SessionSummary | None:
        """No summary available for raw parser."""
        return None
