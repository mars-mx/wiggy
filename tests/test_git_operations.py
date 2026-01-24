"""Tests for git operations (push, PR)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wiggy.git import GitOperations, WorktreeInfo


@pytest.fixture
def worktree_info():
    """Create test WorktreeInfo."""
    return WorktreeInfo(
        path=Path("/worktrees/wiggy_abc123"),
        branch="wiggy/abc123",
        hash_id="abc123",
        main_repo=Path("/home/test/repo"),
    )


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for git commands."""
    with patch("wiggy.git.operations.subprocess") as mock:
        yield mock


def test_has_commits_true(mock_subprocess, worktree_info) -> None:
    """Test has_commits returns True when commits exist."""
    mock_subprocess.run.side_effect = [
        MagicMock(returncode=0, stdout="abc123 Some commit\n"),  # git log
        MagicMock(returncode=0, stdout="5\n"),  # rev-list count
    ]

    ops = GitOperations(worktree_info)
    assert ops.has_commits() is True


def test_has_commits_false_no_commits(mock_subprocess, worktree_info) -> None:
    """Test has_commits returns False when no commits."""
    mock_subprocess.run.side_effect = [
        MagicMock(returncode=0, stdout="abc123 Some commit\n"),  # git log
        MagicMock(returncode=0, stdout="0\n"),  # rev-list count
    ]

    ops = GitOperations(worktree_info)
    assert ops.has_commits() is False


def test_has_commits_false_on_error(mock_subprocess, worktree_info) -> None:
    """Test has_commits returns False on git error."""
    mock_subprocess.run.return_value = MagicMock(returncode=1)

    ops = GitOperations(worktree_info)
    assert ops.has_commits() is False


def test_get_commit_count_ahead(mock_subprocess, worktree_info) -> None:
    """Test get_commit_count_ahead returns correct count."""
    mock_subprocess.run.side_effect = [
        MagicMock(returncode=0),  # rev-parse verify main
        MagicMock(returncode=0, stdout="3\n"),  # rev-list count
    ]

    ops = GitOperations(worktree_info)
    assert ops.get_commit_count_ahead("main") == 3


def test_get_commit_count_ahead_fallback(mock_subprocess, worktree_info) -> None:
    """Test get_commit_count_ahead falls back to remote branches."""
    mock_subprocess.run.side_effect = [
        MagicMock(returncode=1),  # rev-parse verify main (fails)
        MagicMock(returncode=0),  # rev-parse verify origin/main
        MagicMock(returncode=0, stdout="2\n"),  # rev-list count
    ]

    ops = GitOperations(worktree_info)
    assert ops.get_commit_count_ahead("main") == 2


def test_push_to_remote_success(mock_subprocess, worktree_info) -> None:
    """Test successful push to remote."""
    mock_subprocess.run.return_value = MagicMock(returncode=0)

    ops = GitOperations(worktree_info)
    assert ops.push_to_remote("origin") is True

    mock_subprocess.run.assert_called_once()
    call_args = mock_subprocess.run.call_args[0][0]
    assert call_args == ["git", "push", "-u", "origin", "wiggy/abc123"]


def test_push_to_remote_failure(mock_subprocess, worktree_info) -> None:
    """Test push failure returns False."""
    mock_subprocess.run.return_value = MagicMock(returncode=1)

    ops = GitOperations(worktree_info)
    assert ops.push_to_remote("origin") is False


def test_push_to_custom_remote(mock_subprocess, worktree_info) -> None:
    """Test push to custom remote."""
    mock_subprocess.run.return_value = MagicMock(returncode=0)

    ops = GitOperations(worktree_info)
    ops.push_to_remote("upstream")

    call_args = mock_subprocess.run.call_args[0][0]
    assert call_args == ["git", "push", "-u", "upstream", "wiggy/abc123"]


def test_create_pull_request_no_gh(mock_subprocess, worktree_info) -> None:
    """Test create_pull_request returns None when gh not available."""
    with patch("wiggy.git.operations.shutil.which") as mock_which:
        mock_which.return_value = None
        ops = GitOperations(worktree_info)
        assert ops.create_pull_request() is None


def test_create_pull_request_success(mock_subprocess, worktree_info) -> None:
    """Test successful PR creation."""
    with patch("wiggy.git.operations.shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/gh"
        mock_subprocess.run.return_value = MagicMock(
            returncode=0,
            stdout="https://github.com/user/repo/pull/123\n",
        )

        ops = GitOperations(worktree_info)
        url = ops.create_pull_request()

        assert url == "https://github.com/user/repo/pull/123"


def test_create_pull_request_with_title(mock_subprocess, worktree_info) -> None:
    """Test PR creation with custom title."""
    with patch("wiggy.git.operations.shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/gh"
        mock_subprocess.run.return_value = MagicMock(
            returncode=0,
            stdout="https://github.com/user/repo/pull/124\n",
        )

        ops = GitOperations(worktree_info)
        ops.create_pull_request(title="Custom PR Title")

        call_args = mock_subprocess.run.call_args[0][0]
        assert "--title" in call_args
        assert "Custom PR Title" in call_args


def test_create_pull_request_failure(mock_subprocess, worktree_info) -> None:
    """Test PR creation failure returns None."""
    with patch("wiggy.git.operations.shutil.which") as mock_which:
        mock_which.return_value = "/usr/bin/gh"
        mock_subprocess.run.return_value = MagicMock(returncode=1)

        ops = GitOperations(worktree_info)
        assert ops.create_pull_request() is None


def test_get_commit_messages(mock_subprocess, worktree_info) -> None:
    """Test get_commit_messages returns commit list."""
    mock_subprocess.run.side_effect = [
        MagicMock(returncode=0),  # rev-parse verify main
        MagicMock(returncode=0, stdout="abc123 First commit\ndef456 Second commit\n"),
    ]

    ops = GitOperations(worktree_info)
    messages = ops.get_commit_messages("main")

    assert len(messages) == 2
    assert "First commit" in messages[0]
    assert "Second commit" in messages[1]


def test_get_commit_messages_empty(mock_subprocess, worktree_info) -> None:
    """Test get_commit_messages returns empty list when no commits."""
    mock_subprocess.run.side_effect = [
        MagicMock(returncode=0),  # rev-parse verify main
        MagicMock(returncode=0, stdout=""),
    ]

    ops = GitOperations(worktree_info)
    messages = ops.get_commit_messages("main")

    assert messages == []
