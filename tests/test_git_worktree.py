"""Tests for git worktree management."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wiggy.git import (
    NotAGitRepoError,
    WorktreeError,
    WorktreeInfo,
    WorktreeManager,
)


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for git commands."""
    with patch("wiggy.git.worktree.subprocess") as mock:
        yield mock


@pytest.fixture
def mock_is_git_repo(mock_subprocess):
    """Configure mock to indicate we're in a git repo."""
    mock_subprocess.run.return_value = MagicMock(
        returncode=0,
        stdout="/home/test/repo\n",
        stderr="",
    )
    return mock_subprocess


def test_is_git_repo_true(mock_subprocess) -> None:
    """Test is_git_repo returns True for git repositories."""
    mock_subprocess.run.return_value = MagicMock(returncode=0)
    assert WorktreeManager.is_git_repo(Path("/some/repo"))
    mock_subprocess.run.assert_called_once()


def test_is_git_repo_false(mock_subprocess) -> None:
    """Test is_git_repo returns False for non-git directories."""
    mock_subprocess.run.return_value = MagicMock(returncode=128)
    assert not WorktreeManager.is_git_repo(Path("/not/a/repo"))


def test_get_repo_root(mock_subprocess) -> None:
    """Test get_repo_root returns the repository root path."""
    mock_subprocess.run.return_value = MagicMock(
        returncode=0,
        stdout="/home/test/my-repo\n",
    )
    root = WorktreeManager.get_repo_root(Path("/home/test/my-repo/src"))
    assert root == Path("/home/test/my-repo")


def test_manager_init_not_git_repo(mock_subprocess) -> None:
    """Test WorktreeManager raises NotAGitRepoError for non-git directories."""
    mock_subprocess.run.return_value = MagicMock(returncode=128)
    with pytest.raises(NotAGitRepoError):
        WorktreeManager(Path("/not/a/repo"))


def test_manager_init_success(mock_is_git_repo) -> None:
    """Test WorktreeManager initializes successfully in a git repo."""
    manager = WorktreeManager(Path("/home/test/repo"))
    assert manager._repo_root == Path("/home/test/repo")


def test_generate_branch_name(mock_is_git_repo) -> None:
    """Test branch name generation follows format."""
    manager = WorktreeManager(Path("/home/test/repo"))
    branch, hash_id = manager.generate_branch_name()

    assert branch.startswith("wiggy/")
    assert len(hash_id) == 8  # 4 bytes = 8 hex chars
    assert branch == f"wiggy/{hash_id}"


def test_generate_branch_name_with_suffix(mock_is_git_repo) -> None:
    """Test branch name with suffix."""
    manager = WorktreeManager(Path("/home/test/repo"))
    branch, hash_id = manager.generate_branch_name(suffix="exec1")

    assert branch.startswith("wiggy/")
    assert branch.endswith("_exec1")
    assert branch == f"wiggy/{hash_id}_exec1"


def test_get_worktree_root_default(mock_is_git_repo) -> None:
    """Test default worktree root is in ~/.wiggy/worktrees/<repo-name>/."""
    manager = WorktreeManager(Path("/home/test/repo"))
    root = manager.get_worktree_root()

    assert root == Path.home() / ".wiggy" / "worktrees" / "repo"


def test_get_worktree_root_override(mock_is_git_repo) -> None:
    """Test worktree root can be overridden."""
    manager = WorktreeManager(Path("/home/test/repo"))
    override = Path("/custom/worktrees")
    root = manager.get_worktree_root(override)

    assert root == override.resolve()


def test_get_worktree_root_env_var(mock_is_git_repo, monkeypatch) -> None:
    """Test WIGGY_WORKTREE_ROOT environment variable is respected."""
    monkeypatch.setenv("WIGGY_WORKTREE_ROOT", "/env/worktrees")
    manager = WorktreeManager(Path("/home/test/repo"))
    root = manager.get_worktree_root()

    assert root == Path("/env/worktrees").resolve()


def test_create_worktree_success(mock_subprocess) -> None:
    """Test successful worktree creation."""
    # First call: is_git_repo check
    # Second call: get_repo_root
    # Third call: git worktree add
    mock_subprocess.run.side_effect = [
        MagicMock(returncode=0),  # is_git_repo
        MagicMock(returncode=0, stdout="/home/test/repo\n"),  # get_repo_root
        MagicMock(returncode=0, stdout="", stderr=""),  # worktree add
    ]

    manager = WorktreeManager(Path("/home/test/repo"))
    info = manager.create_worktree()

    assert info.branch.startswith("wiggy/")
    assert info.main_repo == Path("/home/test/repo")
    assert "wiggy_" in str(info.path)


def test_create_worktree_failure(mock_subprocess) -> None:
    """Test worktree creation failure raises WorktreeError."""
    mock_subprocess.run.side_effect = [
        MagicMock(returncode=0),  # is_git_repo
        MagicMock(returncode=0, stdout="/home/test/repo\n"),  # get_repo_root
        MagicMock(returncode=1, stderr="fatal: branch already exists"),  # worktree add
    ]

    manager = WorktreeManager(Path("/home/test/repo"))
    with pytest.raises(WorktreeError, match="Failed to create worktree"):
        manager.create_worktree()


def test_use_existing_worktree_not_exists(mock_is_git_repo, tmp_path) -> None:
    """Test use_existing_worktree raises for non-existent path."""
    manager = WorktreeManager(Path("/home/test/repo"))
    with pytest.raises(WorktreeError, match="does not exist"):
        manager.use_existing_worktree(tmp_path / "nonexistent")


def test_use_existing_worktree_not_worktree(mock_is_git_repo, tmp_path) -> None:
    """Test use_existing_worktree raises for non-worktree directory."""
    # Create a directory that's not a worktree (no .git file)
    fake_worktree = tmp_path / "fake_worktree"
    fake_worktree.mkdir()

    manager = WorktreeManager(Path("/home/test/repo"))
    with pytest.raises(WorktreeError, match="Not a valid worktree"):
        manager.use_existing_worktree(fake_worktree)


def test_use_existing_worktree_success(mock_subprocess, tmp_path) -> None:
    """Test successful use of existing worktree."""
    # Create a fake worktree with .git file
    fake_worktree = tmp_path / "my_worktree"
    fake_worktree.mkdir()
    (fake_worktree / ".git").write_text("gitdir: /home/test/repo/.git/worktrees/my")

    mock_subprocess.run.side_effect = [
        MagicMock(returncode=0),  # is_git_repo
        MagicMock(returncode=0, stdout="/home/test/repo\n"),  # get_repo_root
        MagicMock(returncode=0, stdout="wiggy/abc123_exec1\n"),  # get branch
    ]

    manager = WorktreeManager(Path("/home/test/repo"))
    info = manager.use_existing_worktree(fake_worktree)

    assert info.path == fake_worktree.resolve()
    assert info.branch == "wiggy/abc123_exec1"
    assert info.hash_id == "abc123"


def test_remove_worktree_success(mock_subprocess) -> None:
    """Test successful worktree removal."""
    mock_subprocess.run.side_effect = [
        MagicMock(returncode=0),  # is_git_repo
        MagicMock(returncode=0, stdout="/home/test/repo\n"),  # get_repo_root
        MagicMock(returncode=0),  # worktree remove
        MagicMock(returncode=0),  # branch delete
    ]

    manager = WorktreeManager(Path("/home/test/repo"))
    info = WorktreeInfo(
        path=Path("/worktrees/wiggy_abc123"),
        branch="wiggy/abc123",
        hash_id="abc123",
        main_repo=Path("/home/test/repo"),
    )
    manager.remove_worktree(info)

    # Check worktree remove was called
    calls = mock_subprocess.run.call_args_list
    assert ["git", "worktree", "remove", "/worktrees/wiggy_abc123"] in [
        list(c[0][0]) for c in calls
    ]


def test_worktree_info_frozen() -> None:
    """Test WorktreeInfo is immutable."""
    from dataclasses import FrozenInstanceError

    info = WorktreeInfo(
        path=Path("/test"),
        branch="wiggy/test",
        hash_id="12345678",
        main_repo=Path("/repo"),
    )

    with pytest.raises(FrozenInstanceError):
        info.branch = "other"  # type: ignore
