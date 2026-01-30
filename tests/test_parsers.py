"""Tests for output parsers."""

import json

from wiggy.parsers import (
    ClaudeParser,
    MessageType,
    RawParser,
    get_parser_for_engine,
)


class TestClaudeParser:
    """Tests for Claude parser."""

    def test_parse_wiggy_log(self) -> None:
        """Test parsing wiggy_log messages."""
        parser = ClaudeParser()
        line = '{"type":"wiggy_log","message":"Test message"}'
        result = parser.parse_line(line)

        assert result.message_type == MessageType.WIGGY_LOG
        assert result.content == "Test message"
        assert result.is_error is False

    def test_parse_wiggy_error(self) -> None:
        """Test parsing wiggy_error messages."""
        parser = ClaudeParser()
        line = '{"type":"wiggy_error","message":"Something went wrong"}'
        result = parser.parse_line(line)

        assert result.message_type == MessageType.WIGGY_ERROR
        assert result.content == "Something went wrong"
        assert result.is_error is True

    def test_parse_system_init(self) -> None:
        """Test parsing system init messages."""
        parser = ClaudeParser()
        line = json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "session_id": "sess_123",
                "model": "claude-opus-4-5-20251101",
            }
        )
        result = parser.parse_line(line)

        assert result.message_type == MessageType.SYSTEM_INIT
        assert "sess_123" in result.content

    def test_parse_assistant_message(self) -> None:
        """Test parsing assistant messages."""
        parser = ClaudeParser()
        line = json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "Hello world"}]},
            }
        )
        result = parser.parse_line(line)

        assert result.message_type == MessageType.ASSISTANT
        assert result.content == "Hello world"

    def test_parse_assistant_message_multiple_text_blocks(self) -> None:
        """Test parsing assistant messages with multiple text blocks."""
        parser = ClaudeParser()
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "First part"},
                        {"type": "tool_use", "name": "Read"},
                        {"type": "text", "text": "Second part"},
                    ]
                },
            }
        )
        result = parser.parse_line(line)

        assert result.message_type == MessageType.ASSISTANT
        assert result.content == "First part\nSecond part"

    def test_parse_result_success(self) -> None:
        """Test parsing success result."""
        parser = ClaudeParser()
        line = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "result": "Task completed successfully",
                "total_cost_usd": 0.05,
                "duration_ms": 12500,
                "usage": {"input_tokens": 100, "output_tokens": 50},
            }
        )
        result = parser.parse_line(line)

        assert result.message_type == MessageType.RESULT
        assert result.is_final is True
        assert result.is_error is False
        assert "Task completed successfully" in result.content

    def test_parse_result_error(self) -> None:
        """Test parsing error result."""
        parser = ClaudeParser()
        line = json.dumps(
            {
                "type": "result",
                "subtype": "error_max_turns",
            }
        )
        result = parser.parse_line(line)

        assert result.message_type == MessageType.RESULT
        assert result.is_final is True
        assert result.is_error is True

    def test_parse_non_json(self) -> None:
        """Test parsing non-JSON lines."""
        parser = ClaudeParser()
        result = parser.parse_line("Some plain text")

        assert result.message_type == MessageType.RAW
        assert result.content == "Some plain text"

    def test_parse_strips_ansi_escape_sequences(self) -> None:
        """Test that ANSI escape sequences are stripped from non-JSON lines."""
        parser = ClaudeParser()
        # \x1b[?25h is the "show cursor" escape sequence
        result = parser.parse_line("\x1b[?25h")

        assert result.message_type == MessageType.RAW
        assert result.content == ""
        assert result.raw == "\x1b[?25h"  # raw preserves original

    def test_parse_strips_ansi_from_mixed_content(self) -> None:
        """Test ANSI is stripped but text content is preserved."""
        parser = ClaudeParser()
        # Text with color codes
        result = parser.parse_line("\x1b[32mGreen text\x1b[0m")

        assert result.message_type == MessageType.RAW
        assert result.content == "Green text"

    def test_parse_strips_osc_sequences(self) -> None:
        """Test OSC (Operating System Command) sequences are stripped."""
        parser = ClaudeParser()
        # OSC sequence for window title (ends with BEL)
        result = parser.parse_line("\x1b]0;Window Title\x07")

        assert result.message_type == MessageType.RAW
        assert result.content == ""

    def test_parse_strips_progress_osc(self) -> None:
        """Test progress indicator OSC sequences are stripped."""
        parser = ClaudeParser()
        # ConEmu/iTerm2 progress indicator: \x1b]9;4;0;100\x07
        result = parser.parse_line("\x1b]9;4;0;100\x07")

        assert result.message_type == MessageType.RAW
        assert result.content == ""

    def test_parse_empty_line(self) -> None:
        """Test parsing empty lines."""
        parser = ClaudeParser()
        result = parser.parse_line("   ")

        assert result.message_type == MessageType.RAW
        assert result.content == ""

    def test_get_summary(self) -> None:
        """Test summary extraction."""
        parser = ClaudeParser()

        # First parse init to capture session info
        parser.parse_line(
            json.dumps(
                {
                    "type": "system",
                    "subtype": "init",
                    "session_id": "sess_123",
                    "model": "claude-opus-4-5-20251101",
                }
            )
        )

        # Then parse result
        parser.parse_line(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "total_cost_usd": 0.05,
                    "duration_ms": 12500,
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                }
            )
        )

        summary = parser.get_summary()
        assert summary is not None
        assert summary.session_id == "sess_123"
        assert summary.model == "claude-opus-4-5-20251101"
        assert summary.total_cost == 0.05
        assert summary.duration_ms == 12500
        assert summary.input_tokens == 100
        assert summary.output_tokens == 50
        assert summary.success is True

    def test_get_summary_no_result(self) -> None:
        """Test summary returns None without result message."""
        parser = ClaudeParser()
        parser.parse_line('{"type":"wiggy_log","message":"test"}')

        assert parser.get_summary() is None

    def test_reset(self) -> None:
        """Test parser reset."""
        parser = ClaudeParser()

        # Parse some messages
        parser.parse_line(
            json.dumps(
                {
                    "type": "system",
                    "subtype": "init",
                    "session_id": "sess_123",
                    "model": "claude-opus-4-5-20251101",
                }
            )
        )
        parser.parse_line(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                }
            )
        )

        # Reset
        parser.reset()

        # Summary should be None after reset
        assert parser.get_summary() is None


class TestRawParser:
    """Tests for raw parser."""

    def test_passes_through_unchanged(self) -> None:
        """Test raw parser returns content unchanged."""
        parser = RawParser()
        result = parser.parse_line("Any content here")

        assert result.message_type == MessageType.RAW
        assert result.content == "Any content here"
        assert result.raw == "Any content here"

    def test_no_summary(self) -> None:
        """Test raw parser has no summary."""
        parser = RawParser()
        parser.parse_line("some line")
        assert parser.get_summary() is None


class TestParserRegistry:
    """Tests for parser registry."""

    def test_get_claude_parser(self) -> None:
        """Test getting parser for Claude."""
        parser = get_parser_for_engine("Claude Code")
        assert isinstance(parser, ClaudeParser)

    def test_get_claude_parser_lowercase(self) -> None:
        """Test getting parser for claude (lowercase)."""
        parser = get_parser_for_engine("claude")
        assert isinstance(parser, ClaudeParser)

    def test_unknown_engine_gets_raw(self) -> None:
        """Test unknown engine gets raw parser."""
        parser = get_parser_for_engine("Unknown Engine")
        assert isinstance(parser, RawParser)
