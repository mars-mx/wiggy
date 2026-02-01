"""Tests for the new MCP tool handlers: process state, decisions, git inspection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from wiggy.history import TaskHistoryRepository, TaskLog
from wiggy.mcp.tools import (
    _process_state_store,
    handle_get_commit_log,
    handle_get_git_diff,
    handle_get_process_state,
    handle_set_process_decision,
)
from wiggy.processes.base import OrchestratorDecision

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


@pytest.fixture(autouse=True)
def _clear_state_store() -> None:
    """Clear the process state store before each test."""
    _process_state_store.clear()


# ── get_process_state tests ───────────────────────────────────────────


class TestGetProcessState:
    """Tests for the get_process_state tool handler."""

    def test_no_tasks_returns_error(self, repo: TaskHistoryRepository) -> None:
        result = json.loads(handle_get_process_state(repo, "nonexistent"))
        assert "error" in result

    def test_returns_completed_steps(self, repo: TaskHistoryRepository) -> None:
        task = _make_task(
            task_id="t001",
            task_name="analyse",
            finished_at=datetime.now(UTC).isoformat(),
            success=True,
            exit_code=0,
            duration_ms=5000,
        )
        repo.create(task)

        result = json.loads(handle_get_process_state(repo, "proc5678"))
        assert result["process_id"] == "proc5678"
        assert len(result["completed_steps"]) == 1
        step = result["completed_steps"][0]
        assert step["task_name"] == "analyse"
        assert step["task_id"] == "t001"
        assert step["success"] is True
        assert step["exit_code"] == 0
        assert step["duration_ms"] == 5000

    def test_excludes_unfinished_tasks(self, repo: TaskHistoryRepository) -> None:
        finished = _make_task(
            task_id="t001",
            task_name="step1",
            finished_at=datetime.now(UTC).isoformat(),
            success=True,
            exit_code=0,
            duration_ms=1000,
        )
        running = _make_task(task_id="t002", task_name="step2")
        repo.create(finished)
        repo.create(running)

        result = json.loads(handle_get_process_state(repo, "proc5678"))
        assert len(result["completed_steps"]) == 1
        assert result["completed_steps"][0]["task_id"] == "t001"

    def test_includes_orchestrator_decisions(self, repo: TaskHistoryRepository) -> None:
        task = _make_task(task_id="orch01", task_name="orchestrate")
        repo.create(task)

        decision = OrchestratorDecision(
            phase="post_step",
            step_index=0,
            decision="proceed",
            reasoning="All tests pass",
            task_id="orch01",
            created_at=datetime.now(UTC).isoformat(),
        )
        repo.save_orchestrator_decision("proc5678", decision)

        result = json.loads(handle_get_process_state(repo, "proc5678"))
        assert len(result["orchestrator_decisions"]) == 1
        assert result["orchestrator_decisions"][0]["decision"] == "proceed"

    def test_uses_state_store_for_pending_steps(
        self, repo: TaskHistoryRepository
    ) -> None:
        task = _make_task(
            task_id="t001",
            task_name="step1",
            finished_at=datetime.now(UTC).isoformat(),
            success=True,
            exit_code=0,
            duration_ms=1000,
        )
        repo.create(task)

        _process_state_store["proc5678"] = {
            "process_name": "my-process",
            "current_index": 1,
            "steps": [
                {"task": "step1"},
                {"task": "step2"},
                {"task": "step3"},
            ],
        }

        result = json.loads(handle_get_process_state(repo, "proc5678"))
        assert result["process_name"] == "my-process"
        assert result["current_index"] == 1
        assert len(result["pending_steps"]) == 2
        assert result["pending_steps"][0]["task_name"] == "step2"
        assert result["pending_steps"][1]["task_name"] == "step3"


# ── set_process_decision tests ────────────────────────────────────────


class TestSetProcessDecision:
    """Tests for the set_process_decision tool handler."""

    def test_missing_task_id(self, repo: TaskHistoryRepository) -> None:
        result = json.loads(
            handle_set_process_decision(repo, "proc5678", None, "proceed", "ok")
        )
        assert "error" in result
        assert "X-Wiggy-Task-ID" in result["error"]

    def test_invalid_decision(self, repo: TaskHistoryRepository) -> None:
        result = json.loads(
            handle_set_process_decision(
                repo, "proc5678", "task01", "skip", "want to skip"
            )
        )
        assert "error" in result
        assert "Invalid decision" in result["error"]

    def test_inject_without_steps(self, repo: TaskHistoryRepository) -> None:
        result = json.loads(
            handle_set_process_decision(
                repo, "proc5678", "task01", "inject", "need more work"
            )
        )
        assert "error" in result
        assert "injected_steps is required" in result["error"]

    def test_proceed_with_steps(self, repo: TaskHistoryRepository) -> None:
        result = json.loads(
            handle_set_process_decision(
                repo,
                "proc5678",
                "task01",
                "proceed",
                "looks good",
                injected_steps=[{"task_name": "extra", "prompt": "do stuff"}],
            )
        )
        assert "error" in result
        assert "must not be provided" in result["error"]

    def test_proceed_success(self, repo: TaskHistoryRepository) -> None:
        task = _make_task(task_id="task01")
        repo.create(task)

        result = json.loads(
            handle_set_process_decision(
                repo, "proc5678", "task01", "proceed", "all good"
            )
        )
        assert result["status"] == "ok"
        assert result["decision"] == "proceed"

        # Verify it was persisted
        decisions = repo.get_orchestrator_decisions("proc5678")
        assert len(decisions) == 1
        assert decisions[0].decision == "proceed"
        assert decisions[0].reasoning == "all good"

    def test_inject_success(self, repo: TaskHistoryRepository) -> None:
        task = _make_task(task_id="task01")
        repo.create(task)

        result = json.loads(
            handle_set_process_decision(
                repo,
                "proc5678",
                "task01",
                "inject",
                "need a fix step",
                injected_steps=[{"task_name": "hotfix", "prompt": "fix the bug"}],
            )
        )
        assert result["status"] == "ok"
        assert result["decision"] == "inject"

        decisions = repo.get_orchestrator_decisions("proc5678")
        assert len(decisions) == 1
        assert len(decisions[0].injected_steps) == 1
        assert decisions[0].injected_steps[0].task == "hotfix"
        assert decisions[0].injected_steps[0].prompt == "fix the bug"

    def test_abort_success(self, repo: TaskHistoryRepository) -> None:
        task = _make_task(task_id="task01")
        repo.create(task)

        result = json.loads(
            handle_set_process_decision(
                repo, "proc5678", "task01", "abort", "critical failure"
            )
        )
        assert result["status"] == "ok"
        assert result["decision"] == "abort"

    def test_fk_constraint_failure(self, repo: TaskHistoryRepository) -> None:
        result = json.loads(
            handle_set_process_decision(
                repo, "proc5678", "nonexistent", "proceed", "ok"
            )
        )
        assert "error" in result
        assert "not found in task_log" in result["error"]


# ── get_git_diff tests ────────────────────────────────────────────────


class TestGetGitDiff:
    """Tests for the get_git_diff tool handler."""

    def test_missing_task_id(self, repo: TaskHistoryRepository) -> None:
        result = json.loads(handle_get_git_diff(repo, None, "proc5678"))
        assert "error" in result
        assert "X-Wiggy-Task-ID" in result["error"]

    def test_no_worktree(self, repo: TaskHistoryRepository) -> None:
        result = json.loads(handle_get_git_diff(repo, "nonexistent", "proc5678"))
        assert "error" in result
        assert "No worktree found" in result["error"]

    def test_no_since_commit(self, repo: TaskHistoryRepository) -> None:
        task = _make_task(task_id="t001")
        repo.create(task)

        result = json.loads(handle_get_git_diff(repo, "t001", "proc5678"))
        assert "error" in result
        assert "No commit reference found" in result["error"]

    @patch("wiggy.mcp.tools.subprocess.run")
    def test_successful_diff(
        self, mock_run: object, repo: TaskHistoryRepository
    ) -> None:
        import subprocess as sp
        from unittest.mock import MagicMock

        mock_run_fn = MagicMock()
        mock_run_fn.return_value = sp.CompletedProcess(
            args=[], returncode=0, stdout="diff --git a/f.py b/f.py\n+new line\n", stderr=""
        )
        # Replace the mock with our configured one
        with patch("wiggy.mcp.tools.subprocess.run", mock_run_fn):
            task = _make_task(task_id="t001", worktree="/tmp/wt")
            repo.create(task)

            result = json.loads(
                handle_get_git_diff(repo, "t001", "proc5678", since_commit="abc123")
            )
            assert "diff" in result
            assert result["since_commit"] == "abc123"
            assert result["truncated"] is False
            mock_run_fn.assert_called_once()
            call_args = mock_run_fn.call_args
            assert call_args.kwargs["cwd"] == "/tmp/wt"

    @patch("wiggy.mcp.tools.subprocess.run")
    def test_diff_truncation(
        self, mock_run: object, repo: TaskHistoryRepository
    ) -> None:
        import subprocess as sp
        from unittest.mock import MagicMock

        big_diff = "x" * (60 * 1024)  # 60KB, exceeds 50KB limit
        mock_run_fn = MagicMock()
        mock_run_fn.return_value = sp.CompletedProcess(
            args=[], returncode=0, stdout=big_diff, stderr=""
        )
        with patch("wiggy.mcp.tools.subprocess.run", mock_run_fn):
            task = _make_task(task_id="t001", worktree="/tmp/wt")
            repo.create(task)

            result = json.loads(
                handle_get_git_diff(repo, "t001", "proc5678", since_commit="abc123")
            )
            assert result["truncated"] is True
            assert "note" in result

    @patch("wiggy.mcp.tools.subprocess.run")
    def test_diff_git_error(
        self, mock_run: object, repo: TaskHistoryRepository
    ) -> None:
        import subprocess as sp
        from unittest.mock import MagicMock

        mock_run_fn = MagicMock()
        mock_run_fn.return_value = sp.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="fatal: bad revision"
        )
        with patch("wiggy.mcp.tools.subprocess.run", mock_run_fn):
            task = _make_task(task_id="t001", worktree="/tmp/wt")
            repo.create(task)

            result = json.loads(
                handle_get_git_diff(repo, "t001", "proc5678", since_commit="bad")
            )
            assert "error" in result
            assert "git diff failed" in result["error"]

    def test_uses_earliest_ref_when_no_since(
        self, repo: TaskHistoryRepository
    ) -> None:
        task = _make_task(task_id="t001", worktree="/tmp/wt")
        repo.create(task)
        repo.add_ref("t001", "earliest123")

        import subprocess as sp
        from unittest.mock import MagicMock

        mock_run_fn = MagicMock()
        mock_run_fn.return_value = sp.CompletedProcess(
            args=[], returncode=0, stdout="some diff", stderr=""
        )
        with patch("wiggy.mcp.tools.subprocess.run", mock_run_fn):
            result = json.loads(handle_get_git_diff(repo, "t001", "proc5678"))
            assert result["since_commit"] == "earliest123"


# ── get_commit_log tests ──────────────────────────────────────────────


class TestGetCommitLog:
    """Tests for the get_commit_log tool handler."""

    def test_missing_task_id(self, repo: TaskHistoryRepository) -> None:
        result = json.loads(handle_get_commit_log(repo, None, "proc5678"))
        assert "error" in result

    def test_no_worktree(self, repo: TaskHistoryRepository) -> None:
        result = json.loads(handle_get_commit_log(repo, "nonexistent", "proc5678"))
        assert "error" in result

    @patch("wiggy.mcp.tools.subprocess.run")
    def test_successful_log(
        self, mock_run: object, repo: TaskHistoryRepository
    ) -> None:
        import subprocess as sp
        from unittest.mock import MagicMock

        mock_run_fn = MagicMock()
        mock_run_fn.return_value = sp.CompletedProcess(
            args=[],
            returncode=0,
            stdout="abc1234 feat: add login\ndef5678 fix: typo\n",
            stderr="",
        )
        with patch("wiggy.mcp.tools.subprocess.run", mock_run_fn):
            task = _make_task(task_id="t001", worktree="/tmp/wt")
            repo.create(task)

            result = json.loads(
                handle_get_commit_log(repo, "t001", "proc5678", since_commit="abc123")
            )
            assert result["since_commit"] == "abc123"
            assert len(result["commits"]) == 2
            assert result["commits"][0]["hash"] == "abc1234"
            assert result["commits"][0]["message"] == "feat: add login"
            assert result["commits"][1]["hash"] == "def5678"
            assert result["commits"][1]["message"] == "fix: typo"

    @patch("wiggy.mcp.tools.subprocess.run")
    def test_empty_log(
        self, mock_run: object, repo: TaskHistoryRepository
    ) -> None:
        import subprocess as sp
        from unittest.mock import MagicMock

        mock_run_fn = MagicMock()
        mock_run_fn.return_value = sp.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch("wiggy.mcp.tools.subprocess.run", mock_run_fn):
            task = _make_task(task_id="t001", worktree="/tmp/wt")
            repo.create(task)

            result = json.loads(
                handle_get_commit_log(repo, "t001", "proc5678", since_commit="abc123")
            )
            assert result["commits"] == []

    @patch("wiggy.mcp.tools.subprocess.run")
    def test_log_git_error(
        self, mock_run: object, repo: TaskHistoryRepository
    ) -> None:
        import subprocess as sp
        from unittest.mock import MagicMock

        mock_run_fn = MagicMock()
        mock_run_fn.return_value = sp.CompletedProcess(
            args=[], returncode=128, stdout="", stderr="fatal: bad object"
        )
        with patch("wiggy.mcp.tools.subprocess.run", mock_run_fn):
            task = _make_task(task_id="t001", worktree="/tmp/wt")
            repo.create(task)

            result = json.loads(
                handle_get_commit_log(repo, "t001", "proc5678", since_commit="bad")
            )
            assert "error" in result
            assert "git log failed" in result["error"]
