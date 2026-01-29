"""Tests for the compression module."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from wiggy.mcp.compression import (
    SYSTEM_PROMPT,
    CompressionError,
    compress_result,
    is_compression_available,
)


class TestIsCompressionAvailable:
    """Tests for is_compression_available."""

    @patch("wiggy.mcp.compression.shutil.which")
    def test_available(self, mock_which: object) -> None:
        from unittest.mock import MagicMock

        assert isinstance(mock_which, MagicMock)
        mock_which.return_value = "/usr/local/bin/claude"
        assert is_compression_available() is True
        mock_which.assert_called_once_with("claude")

    @patch("wiggy.mcp.compression.shutil.which")
    def test_not_available(self, mock_which: object) -> None:
        from unittest.mock import MagicMock

        assert isinstance(mock_which, MagicMock)
        mock_which.return_value = None
        assert is_compression_available() is False
        mock_which.assert_called_once_with("claude")


class TestCompressResult:
    """Tests for compress_result."""

    @patch("wiggy.mcp.compression.subprocess.run")
    def test_success(self, mock_run: object) -> None:
        from unittest.mock import MagicMock

        assert isinstance(mock_run, MagicMock)
        mock_run.return_value = MagicMock(
            stdout="  Summary of the task result.  \n",
            returncode=0,
        )
        mock_run.return_value.check_returncode = MagicMock()

        result = compress_result("Full task output text here")
        assert result == "Summary of the task result."

    @patch("wiggy.mcp.compression.subprocess.run")
    def test_command_args(self, mock_run: object) -> None:
        from unittest.mock import MagicMock

        assert isinstance(mock_run, MagicMock)
        mock_run.return_value = MagicMock(stdout="summary", returncode=0)
        mock_run.return_value.check_returncode = MagicMock()

        compress_result("some text")

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        cmd = call_args[0][0]

        assert cmd[0] == "claude"
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "haiku"
        assert "--print" in cmd
        assert "--tools" in cmd
        assert cmd[cmd.index("--tools") + 1] == ""
        assert "--strict-mcp-config" in cmd
        assert "--system-prompt" in cmd
        assert cmd[cmd.index("--system-prompt") + 1] == SYSTEM_PROMPT

    @patch("wiggy.mcp.compression.subprocess.run")
    def test_passes_input_via_stdin(self, mock_run: object) -> None:
        from unittest.mock import MagicMock

        assert isinstance(mock_run, MagicMock)
        mock_run.return_value = MagicMock(stdout="summary", returncode=0)
        mock_run.return_value.check_returncode = MagicMock()

        input_text = "Full task output text here"
        compress_result(input_text)

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["input"] == input_text

    @patch("wiggy.mcp.compression.subprocess.run")
    def test_timeout(self, mock_run: object) -> None:
        from unittest.mock import MagicMock

        assert isinstance(mock_run, MagicMock)
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=30)

        with pytest.raises(CompressionError, match="timed out after 30s"):
            compress_result("text", timeout=30)

    @patch("wiggy.mcp.compression.subprocess.run")
    def test_failure(self, mock_run: object) -> None:
        from unittest.mock import MagicMock

        assert isinstance(mock_run, MagicMock)
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd="claude",
            stderr="something went wrong",
        )

        with pytest.raises(CompressionError, match="Compression failed"):
            compress_result("text")

    @patch("wiggy.mcp.compression.subprocess.run")
    def test_cli_not_found(self, mock_run: object) -> None:
        from unittest.mock import MagicMock

        assert isinstance(mock_run, MagicMock)
        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(CompressionError, match="not found"):
            compress_result("text")
