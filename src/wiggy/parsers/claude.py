"""Claude Code output parser."""

import json
import re
from typing import Any

from wiggy.parsers.base import Parser
from wiggy.parsers.messages import MessageType, ParsedMessage, SessionSummary

# ANSI escape sequence patterns:
# - CSI: \x1b[...  (Control Sequence Introducer)
# - OSC: \x1b]...  (Operating System Command, ends with BEL or ST)
# - Simple: \x1b followed by single char
_ANSI_ESCAPE_PATTERN = re.compile(
    r"\x1b"
    r"(?:"
    r"\[[0-?]*[ -/]*[@-~]"  # CSI sequences: \x1b[0m, \x1b[?25h, etc.
    r"|\][^\x07\x1b]*(?:\x07|\x1b\\)?"  # OSC sequences: \x1b]0;title\x07
    r"|[@-Z\\-_]"  # Simple escapes: \x1bM, \x1b7, etc.
    r")"
)

# Pattern for orphaned escape sequence fragments (escape char already stripped)
# Matches lines that are purely CSI/OSC parameters like "?25h" or "9;4;0;"
_ORPHAN_ESCAPE_PATTERN = re.compile(r"^[\]?]?[0-9;?]*[a-zA-Z]?;?$")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    result = _ANSI_ESCAPE_PATTERN.sub("", text)
    # Also check if the entire result is an orphaned escape fragment
    if _ORPHAN_ESCAPE_PATTERN.match(result):
        return ""
    return result


class ClaudeParser(Parser):
    """Parser for Claude Code stream-json output."""

    name = "claude"

    def __init__(self) -> None:
        self._summary_data: dict[str, Any] = {}
        self._session_id: str | None = None
        self._model: str | None = None

    def parse_line(self, line: str) -> ParsedMessage:
        """Parse a single line of Claude output."""
        stripped = line.strip()

        if not stripped:
            return ParsedMessage(
                message_type=MessageType.RAW,
                content="",
                raw=line,
            )

        # Try to parse as JSON
        try:
            data = json.loads(stripped)
            return self._parse_json(data, line)
        except json.JSONDecodeError:
            # Not JSON - treat as raw output (strip ANSI escape sequences)
            return ParsedMessage(
                message_type=MessageType.RAW,
                content=_strip_ansi(stripped),
                raw=line,
            )

    def _parse_json(self, data: dict[str, Any], raw: str) -> ParsedMessage:
        """Parse a JSON message from Claude."""
        msg_type = data.get("type", "")

        # Wiggy entrypoint logs (custom type)
        if msg_type == "wiggy_log":
            return ParsedMessage(
                message_type=MessageType.WIGGY_LOG,
                content=data.get("message", ""),
                raw=raw,
                metadata=data,
            )

        if msg_type == "wiggy_error":
            return ParsedMessage(
                message_type=MessageType.WIGGY_ERROR,
                content=data.get("message", ""),
                raw=raw,
                metadata=data,
                is_error=True,
            )

        # Claude system init
        if msg_type == "system":
            subtype = data.get("subtype", "")
            if subtype == "init":
                self._session_id = data.get("session_id")
                self._model = data.get("model")
                return ParsedMessage(
                    message_type=MessageType.SYSTEM_INIT,
                    content=f"Session started: {self._session_id}",
                    raw=raw,
                    metadata=data,
                )

        # Claude assistant message
        if msg_type == "assistant":
            message = data.get("message", {})
            content_blocks = message.get("content", [])
            text_parts = [
                block.get("text", "")
                for block in content_blocks
                if block.get("type") == "text"
            ]
            content = "\n".join(text_parts) if text_parts else ""
            return ParsedMessage(
                message_type=MessageType.ASSISTANT,
                content=content,
                raw=raw,
                metadata=data,
            )

        # Claude result (final message)
        if msg_type == "result":
            self._summary_data = data
            subtype = data.get("subtype", "")
            is_success = subtype == "success"
            result_text = data.get("result", "")
            return ParsedMessage(
                message_type=MessageType.RESULT,
                content=result_text if result_text else f"Result: {subtype}",
                raw=raw,
                metadata=data,
                is_final=True,
                is_error=not is_success,
            )

        # User messages (tool results)
        if msg_type == "user":
            return ParsedMessage(
                message_type=MessageType.USER,
                content="[Tool result]",
                raw=raw,
                metadata=data,
            )

        # Stream events
        if msg_type == "stream_event":
            return ParsedMessage(
                message_type=MessageType.STREAM_EVENT,
                content="",  # Streaming deltas typically not displayed
                raw=raw,
                metadata=data,
            )

        # Unknown JSON type - return as raw (strip ANSI escape sequences)
        return ParsedMessage(
            message_type=MessageType.RAW,
            content=_strip_ansi(raw),
            raw=raw,
            metadata=data,
        )

    def get_summary(self) -> SessionSummary | None:
        """Extract session summary from result message."""
        if not self._summary_data:
            return None

        usage = self._summary_data.get("usage", {})

        return SessionSummary(
            session_id=self._session_id,
            model=self._model,
            total_cost=self._summary_data.get("total_cost_usd"),
            duration_ms=self._summary_data.get("duration_ms"),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            success=self._summary_data.get("subtype") == "success",
            error_message=self._summary_data.get("error"),
        )

    def reset(self) -> None:
        """Reset parser state."""
        self._summary_data = {}
        self._session_id = None
        self._model = None
