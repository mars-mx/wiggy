"""Tests for the MCP server and tool handlers."""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path
from unittest.mock import patch

import pytest

from wiggy.history import TaskHistoryRepository, TaskLog
from wiggy.mcp.compression import CompressionError
from wiggy.mcp.tools import (
    handle_load_result,
    handle_read_result_summary,
    handle_write_result,
)

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a temporary database path."""
    return tmp_path / "history.db"


@pytest.fixture
def repo(temp_db: Path) -> TaskHistoryRepository:
    """Create a repository with temporary database."""
    return TaskHistoryRepository(db_path=temp_db)


def _make_task(
    task_id: str = "abcd1234",
    process_id: str = "proc5678",
    task_name: str | None = None,
    **kwargs: object,
) -> TaskLog:
    """Create a TaskLog for testing."""
    from datetime import datetime

    defaults: dict[str, object] = {
        "branch": "wiggy/test",
        "worktree": "/tmp/worktree",
        "main_repo": "/home/user/project",
        "engine": "claude",
        "created_at": datetime.now(UTC).isoformat(),
    }
    defaults.update(kwargs)
    return TaskLog(
        task_id=task_id,
        process_id=process_id,
        executor_id=1,
        task_name=task_name,
        **defaults,  # type: ignore[arg-type]
    )


# ── write_result tests ───────────────────────────────────────────────


class TestWriteResult:
    """Tests for the write_result tool handler."""

    @patch("wiggy.mcp.tools.is_compression_available", return_value=False)
    def test_stores_in_db(
        self, _mock_comp: object, repo: TaskHistoryRepository
    ) -> None:
        """write_result stores the result in the database."""
        task = _make_task()
        repo.create(task)

        response = handle_write_result(
            repo,
            "abcd1234",
            "All tests passed.",
            key_files=["src/main.py"],
            tags=["test"],
        )
        data = json.loads(response)
        assert data["status"] == "ok"
        assert data["task_id"] == "abcd1234"

        result = repo.get_result_by_task_id("abcd1234")
        assert result is not None
        assert result.result_text == "All tests passed."
        assert result.key_files == ("src/main.py",)
        assert result.tags == ("test",)

    @patch("wiggy.mcp.tools.compress_result", return_value="Summary here.")
    @patch("wiggy.mcp.tools.is_compression_available", return_value=True)
    def test_triggers_compression(
        self,
        _mock_avail: object,
        mock_compress: object,
        repo: TaskHistoryRepository,
    ) -> None:
        """write_result calls compress_result when available."""
        from unittest.mock import MagicMock

        assert isinstance(mock_compress, MagicMock)

        task = _make_task()
        repo.create(task)

        handle_write_result(repo, "abcd1234", "Full output text")

        mock_compress.assert_called_once_with("Full output text")

        result = repo.get_result_by_task_id("abcd1234")
        assert result is not None
        assert result.has_summary is True
        assert result.summary_text == "Summary here."

    @patch(
        "wiggy.mcp.tools.compress_result",
        side_effect=CompressionError("timeout"),
    )
    @patch("wiggy.mcp.tools.is_compression_available", return_value=True)
    def test_compression_failure_still_saves(
        self,
        _mock_avail: object,
        _mock_compress: object,
        repo: TaskHistoryRepository,
    ) -> None:
        """Result is saved even when compression fails."""
        task = _make_task()
        repo.create(task)

        response = handle_write_result(repo, "abcd1234", "Some result text")
        data = json.loads(response)
        assert data["status"] == "ok"
        assert data["summary_preview"] == "Compression skipped"

        result = repo.get_result_by_task_id("abcd1234")
        assert result is not None
        assert result.result_text == "Some result text"
        assert result.has_summary is False

    @patch("wiggy.mcp.tools.is_compression_available", return_value=False)
    def test_upsert(self, _mock_comp: object, repo: TaskHistoryRepository) -> None:
        """Calling write_result twice overwrites the previous result."""
        task = _make_task()
        repo.create(task)

        handle_write_result(repo, "abcd1234", "First result")
        handle_write_result(repo, "abcd1234", "Second result", tags=["updated"])

        result = repo.get_result_by_task_id("abcd1234")
        assert result is not None
        assert result.result_text == "Second result"
        assert result.tags == ("updated",)

    def test_missing_task_id(self, repo: TaskHistoryRepository) -> None:
        """Missing task_id returns an error."""
        response = handle_write_result(repo, None, "Some text")
        data = json.loads(response)
        assert "error" in data
        assert "Missing X-Wiggy-Task-ID" in data["error"]


# ── load_result tests ────────────────────────────────────────────────


class TestLoadResult:
    """Tests for the load_result tool handler."""

    def test_by_task_id(self, repo: TaskHistoryRepository) -> None:
        """Load a result by its task_id."""
        task = _make_task()
        repo.create(task)
        repo.create_result(
            "abcd1234",
            result_text="Feature implemented",
            key_files=["src/feature.py"],
            tags=["feature"],
        )

        response = handle_load_result(repo, "proc5678", task_id="abcd1234")
        data = json.loads(response)
        assert data["result_text"] == "Feature implemented"
        assert data["key_files"] == ["src/feature.py"]
        assert data["tags"] == ["feature"]
        assert "created_at" in data

    def test_by_task_name(self, repo: TaskHistoryRepository) -> None:
        """Load a result by task_name within a process."""
        task = _make_task(
            task_id="task0001",
            process_id="proc1111",
            task_name="analyse",
        )
        repo.create(task)
        repo.create_result("task0001", result_text="Analysis complete")

        response = handle_load_result(repo, "proc1111", task_name="analyse")
        data = json.loads(response)
        assert data["result_text"] == "Analysis complete"

    def test_not_found(self, repo: TaskHistoryRepository) -> None:
        """Error returned for non-existent task."""
        response = handle_load_result(repo, "proc0000", task_id="nonexistent")
        data = json.loads(response)
        assert "error" in data
        assert "No result found" in data["error"]
        assert "nonexistent" in data["error"]

    def test_neither_provided(self, repo: TaskHistoryRepository) -> None:
        """Error when neither task_name nor task_id is provided."""
        response = handle_load_result(repo, "proc0000")
        data = json.loads(response)
        assert "error" in data
        assert "At least one of" in data["error"]


# ── read_result_summary tests ────────────────────────────────────────


class TestReadResultSummary:
    """Tests for the read_result_summary tool handler."""

    def test_returns_summary(self, repo: TaskHistoryRepository) -> None:
        """Returns compressed summary when available."""
        task = _make_task()
        repo.create(task)
        repo.create_result(
            "abcd1234",
            result_text="Full result text",
            key_files=["src/main.py"],
        )
        repo.update_summary("abcd1234", "TLDR: tests passed")

        response = handle_read_result_summary(repo, "proc5678", task_id="abcd1234")
        data = json.loads(response)
        assert data["summary_text"] == "TLDR: tests passed"
        assert data["key_files"] == ["src/main.py"]
        assert "created_at" in data

    def test_no_summary(self, repo: TaskHistoryRepository) -> None:
        """Error with guidance when no summary exists."""
        task = _make_task()
        repo.create(task)
        repo.create_result("abcd1234", result_text="Raw output only")

        response = handle_read_result_summary(repo, "proc5678", task_id="abcd1234")
        data = json.loads(response)
        assert "error" in data
        assert "No summary available" in data["error"]
        assert "load_result" in data["error"]

    def test_not_found(self, repo: TaskHistoryRepository) -> None:
        """Error for non-existent task."""
        response = handle_read_result_summary(repo, "proc0000", task_id="nonexistent")
        data = json.loads(response)
        assert "error" in data
        assert "No result found" in data["error"]

    def test_neither_provided(self, repo: TaskHistoryRepository) -> None:
        """Error when neither task_name nor task_id is provided."""
        response = handle_read_result_summary(repo, "proc0000")
        data = json.loads(response)
        assert "error" in data
        assert "At least one of" in data["error"]


# ── Server lifecycle tests ───────────────────────────────────────────


class TestWiggyMCPServer:
    """Tests for WiggyMCPServer start/stop lifecycle."""

    def test_starts_and_stops(self, repo: TaskHistoryRepository) -> None:
        """Server starts, gets a port, and stops cleanly."""
        from wiggy.mcp.server import WiggyMCPServer

        server = WiggyMCPServer(repo, "proc_test")
        port = server.start()

        assert port > 0
        assert server.port == port

        server.stop()
        assert server.port is None

    def test_binds_to_localhost(self, repo: TaskHistoryRepository) -> None:
        """Server binds to 127.0.0.1."""
        import socket

        from wiggy.mcp.server import WiggyMCPServer

        server = WiggyMCPServer(repo, "proc_test")
        port = server.start()

        try:
            # Verify we can connect on localhost
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            assert result == 0
        finally:
            server.stop()
