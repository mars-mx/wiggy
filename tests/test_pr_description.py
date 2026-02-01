"""Tests for PR description generation feature."""

from datetime import UTC, datetime
from pathlib import Path

from wiggy.history import TaskHistoryRepository, TaskLog
from wiggy.processes.base import ProcessRun, ProcessSpec, ProcessStep
from wiggy.templates.loader import (
    get_package_templates_path,
    load_template_from_dir,
)


def make_task(
    task_id: str = "abcd1234",
    process_id: str = "proc5678",
    executor_id: int = 1,
    **kwargs: object,
) -> TaskLog:
    """Create a TaskLog for testing."""
    defaults = {
        "created_at": datetime.now(UTC).isoformat(),
        "branch": "wiggy/test",
        "worktree": "/tmp/worktree",
        "main_repo": "/home/user/project",
        "engine": "claude",
    }
    defaults.update(kwargs)
    return TaskLog(
        task_id=task_id,
        process_id=process_id,
        executor_id=executor_id,
        **defaults,  # type: ignore[arg-type]
    )


class TestPrDescriptionTemplate:
    """Tests for pr_description template discovery and loading."""

    def test_pr_description_template_exists(self) -> None:
        """Test that pr_description template is bundled with package."""
        path = get_package_templates_path() / "pr_description"
        assert path.exists()
        assert (path / "template.yaml").exists()
        assert (path / "content.md").exists()

    def test_load_pr_description_template(self) -> None:
        """Test loading the built-in pr_description template."""
        path = get_package_templates_path() / "pr_description"
        tmpl = load_template_from_dir(path)
        assert tmpl is not None
        assert tmpl.name == "pr_description"
        assert tmpl.format == "markdown"
        assert tmpl.description == "Pull request description template"
        assert "pr" in tmpl.tags
        assert "git" in tmpl.tags
        assert len(tmpl.content) > 0

    def test_pr_description_in_default_templates(self) -> None:
        """Test that pr_description is listed in DEFAULT_TEMPLATES."""
        from wiggy.templates import DEFAULT_TEMPLATES

        assert "pr_description" in DEFAULT_TEMPLATES


class TestProcessRunPrBody:
    """Tests for pr_body field on ProcessRun."""

    def test_pr_body_defaults_to_none(self) -> None:
        """Test that pr_body is None by default."""
        spec = ProcessSpec(
            name="test", steps=(ProcessStep(task="implement"),)
        )
        run = ProcessRun(process_id="abc123", spec=spec)
        assert run.pr_body is None

    def test_pr_body_can_be_set(self) -> None:
        """Test that pr_body can be set after creation."""
        spec = ProcessSpec(
            name="test", steps=(ProcessStep(task="implement"),)
        )
        run = ProcessRun(process_id="abc123", spec=spec)
        run.pr_body = "## Summary\n\nSome changes."
        assert run.pr_body == "## Summary\n\nSome changes."


class TestPrBodyFromArtifact:
    """Tests for extracting pr_body from artifacts."""

    def test_pr_body_from_pr_description_artifact(self, tmp_path: Path) -> None:
        """Test that pr_body is populated from a pr_description artifact."""
        db_path = tmp_path / "history.db"
        repo = TaskHistoryRepository(db_path=db_path)

        task = make_task(task_id="t001", process_id="proc001")
        repo.create(task)

        # Simulate writing a pr_description artifact
        repo.create_artifact(
            task_id="t001",
            title="PR Description",
            content="## Summary\n\nAdded feature X.",
            fmt="markdown",
            template_name="pr_description",
            tags=["pr"],
        )

        # Query artifacts as the orchestrator would
        artifacts = repo.get_artifacts_by_process_id("proc001")
        pr_body = None
        for artifact in reversed(artifacts):
            if artifact.template_name == "pr_description":
                pr_body = artifact.content
                break

        assert pr_body == "## Summary\n\nAdded feature X."

    def test_pr_body_none_when_no_artifact(self, tmp_path: Path) -> None:
        """Test that pr_body stays None when no pr_description artifact exists."""
        db_path = tmp_path / "history.db"
        repo = TaskHistoryRepository(db_path=db_path)

        task = make_task(task_id="t002", process_id="proc002")
        repo.create(task)

        artifacts = repo.get_artifacts_by_process_id("proc002")
        pr_body = None
        for artifact in reversed(artifacts):
            if artifact.template_name == "pr_description":
                pr_body = artifact.content
                break

        assert pr_body is None

    def test_pr_body_uses_latest_artifact(self, tmp_path: Path) -> None:
        """Test that the most recent pr_description artifact is used."""
        db_path = tmp_path / "history.db"
        repo = TaskHistoryRepository(db_path=db_path)

        task = make_task(task_id="t003", process_id="proc003")
        repo.create(task)

        repo.create_artifact(
            task_id="t003",
            title="PR Description v1",
            content="First version",
            fmt="markdown",
            template_name="pr_description",
        )
        repo.create_artifact(
            task_id="t003",
            title="PR Description v2",
            content="Second version",
            fmt="markdown",
            template_name="pr_description",
        )

        artifacts = repo.get_artifacts_by_process_id("proc003")
        pr_body = None
        for artifact in reversed(artifacts):
            if artifact.template_name == "pr_description":
                pr_body = artifact.content
                break

        assert pr_body == "Second version"
