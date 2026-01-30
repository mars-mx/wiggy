"""Tests for the task CLI commands."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from wiggy.cli import main


def test_task_list_shows_tasks(tmp_path: Path) -> None:
    """Test that 'wiggy task list' shows available tasks."""
    # Create a mock task
    task_dir = tmp_path / ".wiggy" / "tasks" / "test-task"
    task_dir.mkdir(parents=True)
    (task_dir / "task.yaml").write_text(
        "name: test-task\ndescription: A test task\ntools:\n  - '*'"
    )
    (task_dir / "prompt.md").write_text("# Test prompt")

    with (
        patch(
            "wiggy.tasks.loader.get_global_tasks_path",
            return_value=tmp_path / ".wiggy" / "tasks",
        ),
        patch(
            "wiggy.tasks.loader.get_local_tasks_path",
            return_value=tmp_path / "local" / ".wiggy" / "tasks",
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["task", "list"])

    assert result.exit_code == 0
    assert "test-task" in result.output


def test_task_list_no_tasks(tmp_path: Path) -> None:
    """Test that 'wiggy task list' shows message when no tasks found."""
    with (
        patch(
            "wiggy.tasks.loader.get_global_tasks_path",
            return_value=tmp_path / "nonexistent",
        ),
        patch(
            "wiggy.tasks.loader.get_local_tasks_path",
            return_value=tmp_path / "also_nonexistent",
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["task", "list"])

    assert result.exit_code == 0
    assert "No tasks found" in result.output


def test_task_list_verbose(tmp_path: Path) -> None:
    """Test that 'wiggy task list --verbose' shows more details."""
    # Create a mock task
    task_dir = tmp_path / ".wiggy" / "tasks" / "test-task"
    task_dir.mkdir(parents=True)
    (task_dir / "task.yaml").write_text(
        "name: test-task\ndescription: A detailed description\n"
        "tools:\n  - Read\n  - Write"
    )
    (task_dir / "prompt.md").write_text("# Test prompt")

    with (
        patch(
            "wiggy.tasks.loader.get_global_tasks_path",
            return_value=tmp_path / ".wiggy" / "tasks",
        ),
        patch(
            "wiggy.tasks.loader.get_local_tasks_path",
            return_value=tmp_path / "local" / ".wiggy" / "tasks",
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["task", "list", "--verbose"])

    assert result.exit_code == 0
    assert "test-task" in result.output
    assert "detailed description" in result.output
    assert "Read" in result.output


def test_task_run_unknown_shows_error(tmp_path: Path) -> None:
    """Test that running unknown task shows error."""
    with (
        patch(
            "wiggy.tasks.loader.get_global_tasks_path",
            return_value=tmp_path / "nonexistent",
        ),
        patch(
            "wiggy.tasks.loader.get_local_tasks_path",
            return_value=tmp_path / "also_nonexistent",
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["task", "run", "nonexistent-task"])

    assert result.exit_code == 1
    assert "Unknown task" in result.output


def test_task_without_args_shows_help() -> None:
    """Test that 'wiggy task' without args shows help."""
    runner = CliRunner()
    result = runner.invoke(main, ["task"])

    assert result.exit_code == 0
    assert "Run and manage tasks" in result.output or "Usage:" in result.output
