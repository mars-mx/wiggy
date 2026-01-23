"""Base parser interface."""

from abc import ABC, abstractmethod
from collections.abc import Iterator

from wiggy.parsers.messages import ParsedMessage, SessionSummary


class Parser(ABC):
    """Base class for output parsers."""

    name: str

    @abstractmethod
    def parse_line(self, line: str) -> ParsedMessage:
        """Parse a single line of output.

        Args:
            line: Raw output line from engine.

        Returns:
            ParsedMessage with structured data.
        """
        ...

    def parse_lines(self, lines: Iterator[str]) -> Iterator[ParsedMessage]:
        """Parse multiple lines, yielding parsed messages.

        Default implementation calls parse_line for each line.
        Override for parsers that need multi-line context.
        """
        for line in lines:
            yield self.parse_line(line)

    @abstractmethod
    def get_summary(self) -> SessionSummary | None:
        """Get session summary after parsing is complete.

        Returns None if no summary data is available.
        """
        ...

    def reset(self) -> None:
        """Reset parser state for a new session."""
        pass
