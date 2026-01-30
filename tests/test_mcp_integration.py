"""Tests for MCP server lifecycle integration in CLI commands."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wiggy.cli import (
    _build_single_task_mcp_prompt,
    _check_task_result,
    build_mcp_system_prompt,
)
from wiggy.history import TaskHistoryRepository
from wiggy.history.models import TaskLog

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
    from datetime import UTC, datetime

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


# ── MCP Server Lifecycle Tests ───────────────────────────────────────


class TestMCPServerLifecycleInRun:
    """Tests for MCP server lifecycle in `wiggy run`."""

    @patch("wiggy.cli.Monitor")
    @patch("wiggy.cli.get_executors")
    @patch("wiggy.cli.resolve_engine")
    @patch("wiggy.cli.WorktreeManager")
    @patch("wiggy.cli.WiggyMCPServer")
    @patch("wiggy.cli.TaskHistoryRepository")
    @patch("wiggy.cli.load_config")
    @patch("wiggy.cli.resolve_mcp_bind_host", return_value="127.0.0.1")
    def test_mcp_server_lifecycle_in_run(
        self,
        _mock_bind_host: MagicMock,
        mock_load_config: MagicMock,
        mock_repo_cls: MagicMock,
        mock_mcp_cls: MagicMock,
        mock_wt_manager: MagicMock,
        mock_resolve: MagicMock,
        mock_get_executors: MagicMock,
        mock_monitor_cls: MagicMock,
    ) -> None:
        """MCP server start() is called before task execution and stop() after."""
        from click.testing import CliRunner

        from wiggy.cli import main

        # Config mock
        config = MagicMock()
        config.engine = None
        config.executor = None
        config.image = None
        config.parallel = None
        config.model = None
        config.worktree_root = None
        config.push = False
        config.pr = False
        config.remote = None
        config.keep_worktree = None
        mock_load_config.return_value = config

        # Repo mock
        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo

        # MCP server mock
        mock_mcp = MagicMock()
        mock_mcp.start.return_value = 9999
        mock_mcp.port = 9999
        mock_mcp_cls.return_value = mock_mcp

        # Engine mock
        mock_engine = MagicMock()
        mock_engine.name = "claude"
        mock_resolve.return_value = mock_engine

        # Worktree mock
        mock_wt = MagicMock()
        wt_info = MagicMock()
        wt_info.branch = "wiggy/test"
        wt_info.path = Path("/tmp/wt")
        wt_info.main_repo = Path("/home/user/project")
        mock_wt.create_worktree.return_value = wt_info
        mock_wt_manager.return_value = mock_wt

        # Executor mock
        mock_exec = MagicMock()
        mock_exec.executor_id = 1
        mock_exec.task_id = "aabbccdd"
        mock_exec.exit_code = 0
        mock_exec.summary = None
        mock_exec.run.return_value = iter([])
        mock_get_executors.return_value = [mock_exec]

        # Monitor mock
        mock_monitor = MagicMock()
        mock_monitor_cls.return_value = mock_monitor

        runner = CliRunner()
        runner.invoke(main, ["run", "test prompt"])

        # Verify MCP server lifecycle
        mock_mcp.start.assert_called_once()
        mock_mcp.stop.assert_called_once()

        # Verify mcp_port was passed to get_executors
        mock_get_executors.assert_called_once()
        call_kwargs = mock_get_executors.call_args[1]
        assert call_kwargs["mcp_port"] == 9999

    @patch("wiggy.cli.Monitor")
    @patch("wiggy.cli.get_executors")
    @patch("wiggy.cli.resolve_engine")
    @patch("wiggy.cli.WorktreeManager")
    @patch("wiggy.cli.WiggyMCPServer")
    @patch("wiggy.cli.TaskHistoryRepository")
    @patch("wiggy.cli.load_config")
    @patch("wiggy.cli.resolve_mcp_bind_host", return_value="127.0.0.1")
    def test_mcp_server_stop_on_error(
        self,
        _mock_bind_host: MagicMock,
        mock_load_config: MagicMock,
        mock_repo_cls: MagicMock,
        mock_mcp_cls: MagicMock,
        mock_wt_manager: MagicMock,
        mock_resolve: MagicMock,
        mock_get_executors: MagicMock,
        mock_monitor_cls: MagicMock,
    ) -> None:
        """MCP server is stopped even when task execution raises an exception."""
        from click.testing import CliRunner

        from wiggy.cli import main

        # Config mock
        config = MagicMock()
        config.engine = None
        config.executor = None
        config.image = None
        config.parallel = None
        config.model = None
        config.worktree_root = None
        config.push = False
        config.pr = False
        config.remote = None
        config.keep_worktree = None
        mock_load_config.return_value = config

        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo

        mock_mcp = MagicMock()
        mock_mcp.start.return_value = 9999
        mock_mcp.port = 9999
        mock_mcp_cls.return_value = mock_mcp

        mock_engine = MagicMock()
        mock_engine.name = "claude"
        mock_resolve.return_value = mock_engine

        mock_wt = MagicMock()
        wt_info = MagicMock()
        wt_info.branch = "wiggy/test"
        wt_info.path = Path("/tmp/wt")
        wt_info.main_repo = Path("/home/user/project")
        mock_wt.create_worktree.return_value = wt_info
        mock_wt_manager.return_value = mock_wt

        # Executor that raises on run
        mock_exec = MagicMock()
        mock_exec.executor_id = 1
        mock_exec.task_id = "aabbccdd"
        mock_exec.run.side_effect = RuntimeError("boom")
        mock_get_executors.return_value = [mock_exec]

        mock_monitor = MagicMock()
        mock_monitor_cls.return_value = mock_monitor

        runner = CliRunner()
        runner.invoke(main, ["run", "test prompt"])

        # stop() must be called even on error
        mock_mcp.stop.assert_called_once()


class TestMCPServerLifecycleInTaskRun:
    """Tests for MCP server lifecycle in `wiggy task run`."""

    @patch("wiggy.cli.get_executors")
    @patch("wiggy.cli.resolve_engine")
    @patch("wiggy.cli.get_task_by_name")
    @patch("wiggy.cli.WiggyMCPServer")
    @patch("wiggy.cli.TaskHistoryRepository")
    @patch("wiggy.cli.resolve_mcp_bind_host", return_value="127.0.0.1")
    @patch("wiggy.cli.resolve_git_author", return_value=(None, None))
    @patch("wiggy.cli.load_config")
    def test_mcp_server_lifecycle_in_task_run(
        self,
        _mock_load_config: MagicMock,
        _mock_git_author: MagicMock,
        _mock_bind_host: MagicMock,
        mock_repo_cls: MagicMock,
        mock_mcp_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_resolve: MagicMock,
        mock_get_executors: MagicMock,
    ) -> None:
        """MCP server start/stop wraps task run execution."""
        from click.testing import CliRunner

        from wiggy.cli import main

        # Task spec mock
        mock_spec = MagicMock()
        mock_spec.model = None
        mock_spec.tools = None
        mock_spec.source = None
        mock_get_task.return_value = mock_spec

        # Engine mock
        mock_engine = MagicMock()
        mock_engine.name = "claude"
        mock_resolve.return_value = mock_engine

        # Repo mock
        mock_repo = MagicMock()
        mock_repo.get_result_by_task_id.return_value = None
        mock_repo_cls.return_value = mock_repo

        # MCP server mock
        mock_mcp = MagicMock()
        mock_mcp.start.return_value = 8888
        mock_mcp.port = 8888
        mock_mcp_cls.return_value = mock_mcp

        # Executor mock
        mock_exec = MagicMock()
        mock_exec.exit_code = 0
        mock_exec.run.return_value = iter([])
        mock_get_executors.return_value = [mock_exec]

        runner = CliRunner()
        runner.invoke(main, ["task", "run", "analyse"])

        mock_mcp.start.assert_called_once()
        mock_mcp.stop.assert_called_once()

    @patch("wiggy.cli.get_executors")
    @patch("wiggy.cli.resolve_engine")
    @patch("wiggy.cli.get_task_by_name")
    @patch("wiggy.cli.WiggyMCPServer")
    @patch("wiggy.cli.TaskHistoryRepository")
    @patch("wiggy.cli.resolve_mcp_bind_host", return_value="127.0.0.1")
    @patch("wiggy.cli.resolve_git_author", return_value=(None, None))
    @patch("wiggy.cli.load_config")
    def test_mcp_port_passed_to_executor(
        self,
        _mock_load_config: MagicMock,
        _mock_git_author: MagicMock,
        _mock_bind_host: MagicMock,
        mock_repo_cls: MagicMock,
        mock_mcp_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_resolve: MagicMock,
        mock_get_executors: MagicMock,
    ) -> None:
        """Executor receives mcp_port from the MCP server."""
        from click.testing import CliRunner

        from wiggy.cli import main

        mock_spec = MagicMock()
        mock_spec.model = None
        mock_spec.tools = None
        mock_spec.source = None
        mock_get_task.return_value = mock_spec

        mock_engine = MagicMock()
        mock_engine.name = "claude"
        mock_resolve.return_value = mock_engine

        mock_repo = MagicMock()
        mock_repo.get_result_by_task_id.return_value = None
        mock_repo_cls.return_value = mock_repo

        mock_mcp = MagicMock()
        mock_mcp.start.return_value = 7777
        mock_mcp.port = 7777
        mock_mcp_cls.return_value = mock_mcp

        mock_exec = MagicMock()
        mock_exec.exit_code = 0
        mock_exec.run.return_value = iter([])
        mock_get_executors.return_value = [mock_exec]

        runner = CliRunner()
        runner.invoke(main, ["task", "run", "analyse"])

        mock_get_executors.assert_called_once()
        call_kwargs = mock_get_executors.call_args[1]
        assert call_kwargs["mcp_port"] == 7777

    @patch("wiggy.cli.get_executors")
    @patch("wiggy.cli.resolve_engine")
    @patch("wiggy.cli.get_task_by_name")
    @patch("wiggy.cli.WiggyMCPServer")
    @patch("wiggy.cli.TaskHistoryRepository")
    @patch("wiggy.cli.resolve_mcp_bind_host", return_value="127.0.0.1")
    @patch("wiggy.cli.resolve_git_author", return_value=(None, None))
    @patch("wiggy.cli.load_config")
    def test_mcp_server_stop_on_error(
        self,
        _mock_load_config: MagicMock,
        _mock_git_author: MagicMock,
        _mock_bind_host: MagicMock,
        mock_repo_cls: MagicMock,
        mock_mcp_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_resolve: MagicMock,
        mock_get_executors: MagicMock,
    ) -> None:
        """MCP server is stopped even when task execution raises an exception."""
        from click.testing import CliRunner

        from wiggy.cli import main

        mock_spec = MagicMock()
        mock_spec.model = None
        mock_spec.tools = None
        mock_spec.source = None
        mock_get_task.return_value = mock_spec

        mock_engine = MagicMock()
        mock_engine.name = "claude"
        mock_resolve.return_value = mock_engine

        mock_repo = MagicMock()
        mock_repo_cls.return_value = mock_repo

        mock_mcp = MagicMock()
        mock_mcp.start.return_value = 8888
        mock_mcp.port = 8888
        mock_mcp_cls.return_value = mock_mcp

        # Executor that raises
        mock_exec = MagicMock()
        mock_exec.run.side_effect = RuntimeError("task crash")
        mock_get_executors.return_value = [mock_exec]

        runner = CliRunner()
        runner.invoke(main, ["task", "run", "analyse"])

        # stop() must be called even on error
        mock_mcp.stop.assert_called_once()


# ── MCP Tool Allowlist Tests ────────────────────────────────────────


class TestMCPToolAllowlist:
    """Tests for MCP tool names being added to --allowedTools."""

    @patch("wiggy.cli.get_executors")
    @patch("wiggy.cli.resolve_engine")
    @patch("wiggy.cli.get_task_by_name")
    @patch("wiggy.cli.WiggyMCPServer")
    @patch("wiggy.cli.TaskHistoryRepository")
    @patch("wiggy.cli.resolve_mcp_bind_host", return_value="127.0.0.1")
    @patch("wiggy.cli.resolve_git_author", return_value=(None, None))
    @patch("wiggy.cli.load_config")
    def test_mcp_tools_added_to_allowed_tools(
        self,
        _mock_load_config: MagicMock,
        _mock_git_author: MagicMock,
        _mock_bind_host: MagicMock,
        mock_repo_cls: MagicMock,
        mock_mcp_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_resolve: MagicMock,
        mock_get_executors: MagicMock,
    ) -> None:
        """MCP tool names are appended when tools are restricted."""
        from click.testing import CliRunner

        from wiggy.cli import main
        from wiggy.mcp import MCP_TOOL_NAMES

        mock_spec = MagicMock()
        mock_spec.model = None
        mock_spec.tools = ("Read", "Glob", "Grep")
        mock_spec.source = None
        mock_get_task.return_value = mock_spec

        mock_engine = MagicMock()
        mock_engine.name = "claude"
        mock_resolve.return_value = mock_engine

        mock_repo = MagicMock()
        mock_repo.get_result_by_task_id.return_value = None
        mock_repo_cls.return_value = mock_repo

        mock_mcp = MagicMock()
        mock_mcp.start.return_value = 8888
        mock_mcp_cls.return_value = mock_mcp

        mock_exec = MagicMock()
        mock_exec.exit_code = 0
        mock_exec.run.return_value = iter([])
        mock_get_executors.return_value = [mock_exec]

        runner = CliRunner()
        runner.invoke(main, ["task", "run", "docs"])

        call_kwargs = mock_get_executors.call_args[1]
        allowed = call_kwargs["allowed_tools"]

        # Original tools should be present
        assert "Read" in allowed
        assert "Glob" in allowed
        assert "Grep" in allowed
        # MCP tools should also be present
        for mcp_tool in MCP_TOOL_NAMES:
            assert mcp_tool in allowed

    @patch("wiggy.cli.get_executors")
    @patch("wiggy.cli.resolve_engine")
    @patch("wiggy.cli.get_task_by_name")
    @patch("wiggy.cli.WiggyMCPServer")
    @patch("wiggy.cli.TaskHistoryRepository")
    @patch("wiggy.cli.resolve_mcp_bind_host", return_value="127.0.0.1")
    @patch("wiggy.cli.resolve_git_author", return_value=(None, None))
    @patch("wiggy.cli.load_config")
    def test_mcp_tools_not_added_when_wildcard(
        self,
        _mock_load_config: MagicMock,
        _mock_git_author: MagicMock,
        _mock_bind_host: MagicMock,
        mock_repo_cls: MagicMock,
        mock_mcp_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_resolve: MagicMock,
        mock_get_executors: MagicMock,
    ) -> None:
        """MCP tool names are NOT added when tools is wildcard."""
        from click.testing import CliRunner

        from wiggy.cli import main

        mock_spec = MagicMock()
        mock_spec.model = None
        mock_spec.tools = ("*",)
        mock_spec.source = None
        mock_get_task.return_value = mock_spec

        mock_engine = MagicMock()
        mock_engine.name = "claude"
        mock_resolve.return_value = mock_engine

        mock_repo = MagicMock()
        mock_repo.get_result_by_task_id.return_value = None
        mock_repo_cls.return_value = mock_repo

        mock_mcp = MagicMock()
        mock_mcp.start.return_value = 8888
        mock_mcp_cls.return_value = mock_mcp

        mock_exec = MagicMock()
        mock_exec.exit_code = 0
        mock_exec.run.return_value = iter([])
        mock_get_executors.return_value = [mock_exec]

        runner = CliRunner()
        runner.invoke(main, ["task", "run", "analyse"])

        call_kwargs = mock_get_executors.call_args[1]
        assert call_kwargs["allowed_tools"] is None

    @patch("wiggy.cli.get_executors")
    @patch("wiggy.cli.resolve_engine")
    @patch("wiggy.cli.get_task_by_name")
    @patch("wiggy.cli.WiggyMCPServer")
    @patch("wiggy.cli.TaskHistoryRepository")
    @patch("wiggy.cli.resolve_mcp_bind_host", return_value="127.0.0.1")
    @patch("wiggy.cli.resolve_git_author", return_value=(None, None))
    @patch("wiggy.cli.load_config")
    def test_mcp_tools_not_added_when_mcp_fails(
        self,
        _mock_load_config: MagicMock,
        _mock_git_author: MagicMock,
        _mock_bind_host: MagicMock,
        mock_repo_cls: MagicMock,
        mock_mcp_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_resolve: MagicMock,
        mock_get_executors: MagicMock,
    ) -> None:
        """MCP tool names are NOT added when MCP server fails to start."""
        from click.testing import CliRunner

        from wiggy.cli import main

        mock_spec = MagicMock()
        mock_spec.model = None
        mock_spec.tools = ("Read", "Glob")
        mock_spec.source = None
        mock_get_task.return_value = mock_spec

        mock_engine = MagicMock()
        mock_engine.name = "claude"
        mock_resolve.return_value = mock_engine

        mock_repo = MagicMock()
        mock_repo.get_result_by_task_id.return_value = None
        mock_repo_cls.return_value = mock_repo

        mock_mcp = MagicMock()
        mock_mcp.start.side_effect = RuntimeError("bind failed")
        mock_mcp_cls.return_value = mock_mcp

        mock_exec = MagicMock()
        mock_exec.exit_code = 0
        mock_exec.run.return_value = iter([])
        mock_get_executors.return_value = [mock_exec]

        runner = CliRunner()
        runner.invoke(main, ["task", "run", "docs"])

        call_kwargs = mock_get_executors.call_args[1]
        allowed = call_kwargs["allowed_tools"]
        # Only original tools, no MCP tools
        assert allowed == ["Read", "Glob"]


# ── Post-Step Validation Tests ───────────────────────────────────────


class TestPostStepValidation:
    """Tests for _check_task_result post-step validation."""

    def test_with_result_no_warning(
        self, repo: TaskHistoryRepository, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No warning is logged when task has written a result."""
        task = _make_task()
        repo.create(task)
        repo.create_result("abcd1234", result_text="Done")

        with caplog.at_level(logging.WARNING):
            _check_task_result(repo, "abcd1234", "analyse")

        assert "did not call write_result" not in caplog.text

    def test_without_result_warns(
        self, repo: TaskHistoryRepository, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Warning is logged when task did not write a result."""
        task = _make_task()
        repo.create(task)

        with caplog.at_level(logging.WARNING):
            _check_task_result(repo, "abcd1234", "analyse")

        assert "analyse" in caplog.text
        assert "did not call write_result" in caplog.text

    def test_without_result_uses_task_id_when_no_name(
        self, repo: TaskHistoryRepository, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Falls back to task_id when task_name is None."""
        task = _make_task()
        repo.create(task)

        with caplog.at_level(logging.WARNING):
            _check_task_result(repo, "abcd1234", None)

        assert "abcd1234" in caplog.text
        assert "did not call write_result" in caplog.text


# ── System Prompt Tests ──────────────────────────────────────────────


class TestMCPSystemPrompt:
    """Tests for build_mcp_system_prompt and _build_single_task_mcp_prompt."""

    def test_multi_step_prompt(self, repo: TaskHistoryRepository) -> None:
        """Multi-step prompt includes previous step names and current step."""
        prompt = build_mcp_system_prompt(
            process_id="proc5678",
            current_task_name="test",
            completed_steps=["analyse", "implement"],
            repo=repo,
        )

        assert "multi-step process" in prompt
        assert "read_result_summary" in prompt
        assert "write_result" in prompt
        assert "analyse (completed)" in prompt
        assert "implement (completed)" in prompt
        assert "Current step: test" in prompt

    def test_multi_step_no_completed(self, repo: TaskHistoryRepository) -> None:
        """Multi-step prompt works with no completed steps."""
        prompt = build_mcp_system_prompt(
            process_id="proc5678",
            current_task_name="analyse",
            completed_steps=[],
            repo=repo,
        )

        assert "multi-step process" in prompt
        assert "Current step: analyse" in prompt
        assert "Previous steps" not in prompt

    def test_single_task_prompt(self) -> None:
        """Single task prompt includes MCP tool instructions."""
        prompt = _build_single_task_mcp_prompt()

        assert "write_result" in prompt
        assert "read_result_summary" in prompt
        assert "multi-step" not in prompt
