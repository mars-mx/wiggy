"""Tests for task loading and discovery."""

from pathlib import Path
from unittest.mock import patch

import pytest

from wiggy.tasks import (
    DEFAULT_TASKS,
    TaskSpec,
    get_all_tasks,
    get_available_task_names,
    get_task_by_name,
)
from wiggy.tasks.loader import (
    discover_task_dirs,
    load_markdown_files,
    load_task_from_dir,
)


class TestTaskSpec:
    """Tests for TaskSpec dataclass."""

    def test_default_tools_is_all(self) -> None:
        """Test that default tools is all (*)."""
        spec = TaskSpec(name="test", description="Test task")
        assert spec.tools == ("*",)

    def test_default_model_is_none(self) -> None:
        """Test that default model is None."""
        spec = TaskSpec(name="test", description="Test task")
        assert spec.model is None

    def test_default_prompt_template_is_empty(self) -> None:
        """Test that default prompt_template is empty string."""
        spec = TaskSpec(name="test", description="Test task")
        assert spec.prompt_template == ""

    def test_from_dict_creates_spec(self) -> None:
        """Test TaskSpec.from_dict creates a valid spec."""
        data = {
            "name": "implement",
            "description": "Implement feature",
            "tools": ["Read", "Write", "Bash"],
            "model": "opus",
        }
        spec = TaskSpec.from_dict(data)

        assert spec.name == "implement"
        assert spec.description == "Implement feature"
        assert spec.tools == ("Read", "Write", "Bash")
        assert spec.model == "opus"

    def test_from_dict_with_defaults(self) -> None:
        """Test from_dict uses defaults for missing fields."""
        data = {"name": "test", "description": "Test"}
        spec = TaskSpec.from_dict(data)

        assert spec.tools == ("*",)
        assert spec.model is None

    def test_to_dict_excludes_defaults(self) -> None:
        """Test to_dict excludes default values."""
        spec = TaskSpec(name="test", description="Test")
        data = spec.to_dict()

        assert "name" in data
        assert "description" in data
        assert "tools" not in data  # Default is ("*",)
        assert "model" not in data  # Default is None

    def test_to_dict_includes_non_defaults(self) -> None:
        """Test to_dict includes non-default values."""
        spec = TaskSpec(
            name="test",
            description="Test",
            tools=("Read", "Write"),
            model="opus",
        )
        data = spec.to_dict()

        assert data["tools"] == ["Read", "Write"]
        assert data["model"] == "opus"

    def test_with_prompt_returns_new_spec(self) -> None:
        """Test with_prompt returns a new TaskSpec."""
        spec = TaskSpec(name="test", description="Test")
        new_spec = spec.with_prompt("# Prompt content")

        assert new_spec is not spec
        assert new_spec.prompt_template == "# Prompt content"
        assert spec.prompt_template == ""

    def test_with_prompt_preserves_other_fields(self) -> None:
        """Test with_prompt preserves all other fields."""
        spec = TaskSpec(
            name="test",
            description="Test desc",
            tools=("Read",),
            model="opus",
        )
        new_spec = spec.with_prompt("# Prompt")

        assert new_spec.name == "test"
        assert new_spec.description == "Test desc"
        assert new_spec.tools == ("Read",)
        assert new_spec.model == "opus"


class TestMarkdownLoading:
    """Tests for markdown file loading."""

    def test_load_markdown_files_combines_sorted(self, tmp_path: Path) -> None:
        """Test that markdown files are combined in sorted order."""
        task_dir = tmp_path / "test_task"
        task_dir.mkdir()

        (task_dir / "02_second.md").write_text("Second content")
        (task_dir / "01_first.md").write_text("First content")
        (task_dir / "03_third.md").write_text("Third content")

        result = load_markdown_files(task_dir)

        assert result == "First content\n\nSecond content\n\nThird content"

    def test_load_markdown_files_empty_dir(self, tmp_path: Path) -> None:
        """Test loading from directory with no .md files."""
        task_dir = tmp_path / "empty_task"
        task_dir.mkdir()

        result = load_markdown_files(task_dir)

        assert result == ""

    def test_load_markdown_files_skips_empty_files(self, tmp_path: Path) -> None:
        """Test that empty markdown files are skipped."""
        task_dir = tmp_path / "test_task"
        task_dir.mkdir()

        (task_dir / "01_content.md").write_text("Content")
        (task_dir / "02_empty.md").write_text("   ")  # Whitespace only

        result = load_markdown_files(task_dir)

        assert result == "Content"

    def test_load_markdown_files_strips_whitespace(self, tmp_path: Path) -> None:
        """Test that markdown content is stripped."""
        task_dir = tmp_path / "test_task"
        task_dir.mkdir()

        (task_dir / "prompt.md").write_text("  Content  \n\n")

        result = load_markdown_files(task_dir)

        assert result == "Content"


class TestTaskDiscovery:
    """Tests for task discovery."""

    def test_discover_task_dirs_finds_valid_tasks(self, tmp_path: Path) -> None:
        """Test that discover_task_dirs finds directories with task.yaml."""
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()

        # Valid task
        valid_task = tasks_dir / "implement"
        valid_task.mkdir()
        (valid_task / "task.yaml").write_text("name: implement\ndescription: Test")

        # Invalid (no task.yaml)
        invalid_task = tasks_dir / "invalid"
        invalid_task.mkdir()

        result = discover_task_dirs(tasks_dir)

        assert "implement" in result
        assert "invalid" not in result

    def test_discover_task_dirs_nonexistent_path(self, tmp_path: Path) -> None:
        """Test discover_task_dirs returns empty for nonexistent path."""
        result = discover_task_dirs(tmp_path / "nonexistent")
        assert result == {}

    def test_load_task_from_dir(self, tmp_path: Path) -> None:
        """Test loading a complete task from directory."""
        task_dir = tmp_path / "implement"
        task_dir.mkdir()

        (task_dir / "task.yaml").write_text(
            "name: implement\ndescription: Implement feature\ntools:\n  - Read\n  - Write"
        )
        (task_dir / "prompt.md").write_text("# Implementation\n\nDo the thing.")

        spec = load_task_from_dir(task_dir)

        assert spec is not None
        assert spec.name == "implement"
        assert spec.description == "Implement feature"
        assert spec.tools == ("Read", "Write")
        assert "# Implementation" in spec.prompt_template
        assert spec.source == task_dir

    def test_load_task_from_dir_missing_yaml(self, tmp_path: Path) -> None:
        """Test loading returns None if task.yaml is missing."""
        task_dir = tmp_path / "invalid"
        task_dir.mkdir()

        result = load_task_from_dir(task_dir)

        assert result is None


class TestTaskResolution:
    """Tests for task resolution order."""

    def test_local_overrides_global(self, tmp_path: Path) -> None:
        """Test that local tasks override global tasks."""
        global_path = tmp_path / "global" / "tasks"
        local_path = tmp_path / "local" / "tasks"

        # Global task
        global_task = global_path / "implement"
        global_task.mkdir(parents=True)
        (global_task / "task.yaml").write_text(
            "name: implement\ndescription: Global version"
        )

        # Local task (should win)
        local_task = local_path / "implement"
        local_task.mkdir(parents=True)
        (local_task / "task.yaml").write_text(
            "name: implement\ndescription: Local version"
        )

        with (
            patch(
                "wiggy.tasks.loader.get_global_tasks_path", return_value=global_path
            ),
            patch("wiggy.tasks.loader.get_local_tasks_path", return_value=local_path),
            patch(
                "wiggy.tasks.loader.get_package_tasks_path",
                return_value=tmp_path / "pkg",
            ),
        ):
            spec = get_task_by_name("implement")

        assert spec is not None
        assert spec.description == "Local version"

    def test_global_overrides_package(self, tmp_path: Path) -> None:
        """Test that global tasks override package tasks."""
        package_path = tmp_path / "package" / "tasks"
        global_path = tmp_path / "global" / "tasks"
        local_path = tmp_path / "local" / "tasks"

        # Package task
        package_task = package_path / "analyse"
        package_task.mkdir(parents=True)
        (package_task / "task.yaml").write_text(
            "name: analyse\ndescription: Package version"
        )

        # Global task (should win)
        global_task = global_path / "analyse"
        global_task.mkdir(parents=True)
        (global_task / "task.yaml").write_text(
            "name: analyse\ndescription: Global version"
        )

        with (
            patch(
                "wiggy.tasks.loader.get_global_tasks_path", return_value=global_path
            ),
            patch("wiggy.tasks.loader.get_local_tasks_path", return_value=local_path),
            patch(
                "wiggy.tasks.loader.get_package_tasks_path", return_value=package_path
            ),
        ):
            spec = get_task_by_name("analyse")

        assert spec is not None
        assert spec.description == "Global version"


class TestDefaultTasks:
    """Tests for default tasks."""

    def test_default_tasks_constant(self) -> None:
        """Test DEFAULT_TASKS contains expected tasks."""
        assert "analyse" in DEFAULT_TASKS
        assert "research" in DEFAULT_TASKS
        assert "implement" in DEFAULT_TASKS
        assert "test" in DEFAULT_TASKS
        assert "review" in DEFAULT_TASKS

    def test_package_default_tasks_exist(self) -> None:
        """Test that package default tasks can be loaded."""
        tasks = get_all_tasks()

        # Should have at least the 5 default tasks
        assert len(tasks) >= 5
        for task_name in DEFAULT_TASKS:
            assert task_name in tasks

    def test_default_tasks_have_prompts(self) -> None:
        """Test that default tasks have non-empty prompts."""
        for task_name in DEFAULT_TASKS:
            spec = get_task_by_name(task_name)
            assert spec is not None, f"Task {task_name} not found"
            assert spec.prompt_template, f"Task {task_name} has no prompt"

    def test_default_tasks_have_all_tools(self) -> None:
        """Test that default tasks have all tools enabled."""
        for task_name in DEFAULT_TASKS:
            spec = get_task_by_name(task_name)
            assert spec is not None
            assert spec.tools == ("*",), f"Task {task_name} should have all tools"

    def test_get_available_task_names(self) -> None:
        """Test get_available_task_names returns sorted list."""
        names = get_available_task_names()

        assert isinstance(names, list)
        assert names == sorted(names)
        for task_name in DEFAULT_TASKS:
            assert task_name in names
