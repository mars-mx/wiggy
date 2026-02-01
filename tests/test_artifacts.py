"""Tests for artifacts and artifact templates."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wiggy.history import Artifact, TaskHistoryRepository, TaskLog
from wiggy.history.schema import SCHEMA_VERSION
from wiggy.mcp.tools import (
    VALID_FORMATS,
    handle_list_artifact_templates,
    handle_list_artifacts,
    handle_load_artifact,
    handle_load_artifact_template,
    handle_write_artifact,
)
from wiggy.templates.base import ArtifactTemplate
from wiggy.templates.loader import (
    discover_template_dirs,
    get_package_templates_path,
    load_template_from_dir,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a temporary database path."""
    return tmp_path / "history.db"


@pytest.fixture
def repo(temp_db: Path) -> TaskHistoryRepository:
    """Create a repository with temporary database."""
    return TaskHistoryRepository(db_path=temp_db)


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


class TestArtifactTemplate:
    """Tests for ArtifactTemplate dataclass."""

    def test_create_template(self) -> None:
        """Test creating an ArtifactTemplate."""
        tmpl = ArtifactTemplate(
            name="prd",
            description="Product Requirements Document",
            format="markdown",
            content="# PRD\n\n## Overview",
            tags=("requirements", "planning"),
        )
        assert tmpl.name == "prd"
        assert tmpl.format == "markdown"
        assert tmpl.tags == ("requirements", "planning")
        assert tmpl.source is None

    def test_template_frozen(self) -> None:
        """Test that ArtifactTemplate is immutable."""
        tmpl = ArtifactTemplate(
            name="test", description="desc", format="text", content="body"
        )
        with pytest.raises(AttributeError):
            tmpl.name = "changed"  # type: ignore[misc]


class TestTemplateLoader:
    """Tests for template discovery and loading."""

    def test_package_templates_exist(self) -> None:
        """Test that default templates are bundled with package."""
        path = get_package_templates_path()
        assert path.exists()
        dirs = discover_template_dirs(path)
        assert "prd" in dirs
        assert "documentation" in dirs

    def test_load_prd_template(self) -> None:
        """Test loading the built-in PRD template."""
        path = get_package_templates_path() / "prd"
        tmpl = load_template_from_dir(path)
        assert tmpl is not None
        assert tmpl.name == "prd"
        assert tmpl.format == "markdown"
        assert tmpl.description == "Product Requirements Document template"
        assert "requirements" in tmpl.tags
        assert len(tmpl.content) > 0

    def test_load_documentation_template(self) -> None:
        """Test loading the built-in documentation template."""
        path = get_package_templates_path() / "documentation"
        tmpl = load_template_from_dir(path)
        assert tmpl is not None
        assert tmpl.name == "documentation"
        assert tmpl.format == "markdown"
        assert len(tmpl.content) > 0

    def test_load_nonexistent_template(self, tmp_path: Path) -> None:
        """Test loading from a directory without template.yaml returns None."""
        tmpl = load_template_from_dir(tmp_path / "nonexistent")
        assert tmpl is None

    def test_discover_empty_directory(self, tmp_path: Path) -> None:
        """Test discovering templates in an empty directory."""
        dirs = discover_template_dirs(tmp_path)
        assert dirs == {}

    def test_discover_template_dirs(self, tmp_path: Path) -> None:
        """Test discovering template directories."""
        # Create a template dir
        tmpl_dir = tmp_path / "my-template"
        tmpl_dir.mkdir()
        (tmpl_dir / "template.yaml").write_text(
            "name: my-template\ndescription: Test\nformat: text\n"
        )
        (tmpl_dir / "content.txt").write_text("Hello")

        dirs = discover_template_dirs(tmp_path)
        assert "my-template" in dirs

    def test_load_template_from_custom_dir(self, tmp_path: Path) -> None:
        """Test loading a template from a custom directory."""
        tmpl_dir = tmp_path / "custom"
        tmpl_dir.mkdir()
        (tmpl_dir / "template.yaml").write_text(
            "name: custom\ndescription: Custom template\n"
            "format: json\ntags:\n  - test\n"
        )
        (tmpl_dir / "content.json").write_text('{"key": "value"}')

        tmpl = load_template_from_dir(tmpl_dir)
        assert tmpl is not None
        assert tmpl.name == "custom"
        assert tmpl.format == "json"
        assert tmpl.tags == ("test",)
        assert tmpl.content == '{"key": "value"}'


class TestArtifactModel:
    """Tests for Artifact dataclass."""

    def test_create_artifact(self) -> None:
        """Test creating an Artifact."""
        artifact = Artifact(
            id="art12345",
            task_id="task1234",
            title="Analysis Report",
            content="# Report\n\nFindings here.",
            format="markdown",
            tags=("analysis", "report"),
            created_at="2024-01-01T00:00:00Z",
            template_name="documentation",
        )
        assert artifact.id == "art12345"
        assert artifact.task_id == "task1234"
        assert artifact.format == "markdown"
        assert artifact.template_name == "documentation"

    def test_artifact_frozen(self) -> None:
        """Test that Artifact is immutable."""
        artifact = Artifact(
            id="a",
            task_id="t",
            title="T",
            content="C",
            format="text",
            tags=(),
            created_at="2024-01-01T00:00:00Z",
        )
        with pytest.raises(AttributeError):
            artifact.title = "changed"  # type: ignore[misc]


class TestArtifactRepository:
    """Tests for artifact CRUD in TaskHistoryRepository."""

    def test_create_artifact(self, repo: TaskHistoryRepository) -> None:
        """Test creating and retrieving an artifact."""
        task = make_task()
        repo.create(task)

        artifact = repo.create_artifact(
            task_id="abcd1234",
            title="Test Artifact",
            content="Hello world",
            fmt="text",
            tags=["test"],
        )
        assert artifact.id  # non-empty
        assert artifact.task_id == "abcd1234"
        assert artifact.title == "Test Artifact"
        assert artifact.content == "Hello world"
        assert artifact.format == "text"
        assert artifact.tags == ("test",)
        assert artifact.template_name is None

    def test_create_artifact_with_template(self, repo: TaskHistoryRepository) -> None:
        """Test creating an artifact with a template name."""
        task = make_task()
        repo.create(task)

        artifact = repo.create_artifact(
            task_id="abcd1234",
            title="PRD: Feature X",
            content="# PRD\n\n## Overview",
            fmt="markdown",
            template_name="prd",
            tags=["requirements"],
        )
        assert artifact.template_name == "prd"

    def test_get_artifact_by_id(self, repo: TaskHistoryRepository) -> None:
        """Test retrieving an artifact by ID."""
        task = make_task()
        repo.create(task)

        created = repo.create_artifact(
            task_id="abcd1234",
            title="My Doc",
            content="Content here",
            fmt="markdown",
        )

        retrieved = repo.get_artifact_by_id(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.title == "My Doc"
        assert retrieved.content == "Content here"

    def test_get_artifact_by_id_not_found(self, repo: TaskHistoryRepository) -> None:
        """Test get_artifact_by_id returns None for nonexistent ID."""
        result = repo.get_artifact_by_id("nonexistent")
        assert result is None

    def test_get_artifacts_by_task_id(self, repo: TaskHistoryRepository) -> None:
        """Test retrieving multiple artifacts for a task."""
        task = make_task()
        repo.create(task)

        repo.create_artifact(
            task_id="abcd1234", title="Doc 1", content="First", fmt="text"
        )
        repo.create_artifact(
            task_id="abcd1234", title="Doc 2", content="Second", fmt="text"
        )

        artifacts = repo.get_artifacts_by_task_id("abcd1234")
        assert len(artifacts) == 2
        titles = {a.title for a in artifacts}
        assert titles == {"Doc 1", "Doc 2"}

    def test_get_artifacts_by_task_id_empty(self, repo: TaskHistoryRepository) -> None:
        """Test empty list for task with no artifacts."""
        task = make_task()
        repo.create(task)

        artifacts = repo.get_artifacts_by_task_id("abcd1234")
        assert artifacts == []

    def test_get_artifacts_by_process_id(self, repo: TaskHistoryRepository) -> None:
        """Test retrieving artifacts across all tasks in a process."""
        task1 = make_task(task_id="task0001", process_id="proc1111", executor_id=1)
        task2 = make_task(task_id="task0002", process_id="proc1111", executor_id=2)
        repo.create(task1)
        repo.create(task2)

        repo.create_artifact(
            task_id="task0001", title="From Task 1", content="A", fmt="text"
        )
        repo.create_artifact(
            task_id="task0002", title="From Task 2", content="B", fmt="text"
        )

        artifacts = repo.get_artifacts_by_process_id("proc1111")
        assert len(artifacts) == 2
        titles = {a.title for a in artifacts}
        assert titles == {"From Task 1", "From Task 2"}

    def test_cascade_delete(self, repo: TaskHistoryRepository) -> None:
        """Test that deleting a task cascades to its artifacts."""
        task = make_task()
        repo.create(task)

        created = repo.create_artifact(
            task_id="abcd1234", title="Will be deleted", content="X", fmt="text"
        )

        repo.delete_task("abcd1234")
        assert repo.get_artifact_by_id(created.id) is None


class TestSchemaVersion:
    """Test schema version is correct after adding artifact table."""

    def test_schema_version_is_5(self) -> None:
        """Test that SCHEMA_VERSION is 5."""
        assert SCHEMA_VERSION == 5

    def test_fresh_install_has_artifact_table(self, tmp_path: Path) -> None:
        """Test that fresh database includes the artifact table."""
        import sqlite3

        db_path = tmp_path / "fresh.db"
        TaskHistoryRepository(db_path=db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "artifact" in tables

    def test_migration_v2_to_v4(self, tmp_path: Path) -> None:
        """Test migrating a v2 database to v4 adds the artifact table."""
        import sqlite3

        from wiggy.history.schema import SCHEMA_SQL, get_schema_version

        db_path = tmp_path / "migrate.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Build a v2 database (everything except the artifact table)
        v2_sql = SCHEMA_SQL.split("-- Artifact documents per task")[0]
        conn.executescript(v2_sql)
        conn.execute("INSERT INTO schema_version VALUES (2)")
        conn.commit()

        assert get_schema_version(conn) == 2
        conn.close()

        # Open via repository — triggers migration
        TaskHistoryRepository(db_path=db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master"
            " WHERE type='table' AND name='artifact'"
        )
        assert cursor.fetchone() is not None
        assert get_schema_version(conn) == SCHEMA_VERSION
        conn.close()


class TestMCPArtifactHandlers:
    """Tests for MCP tool handler functions for artifacts."""

    def test_handle_write_artifact(self, repo: TaskHistoryRepository) -> None:
        """Test writing an artifact via MCP handler."""
        task = make_task()
        repo.create(task)

        result = json.loads(
            handle_write_artifact(
                repo,
                task_id="abcd1234",
                title="Test",
                content="Body",
                fmt="text",
            )
        )
        assert result["status"] == "ok"
        assert result["artifact_id"]
        assert result["title"] == "Test"

    def test_handle_write_artifact_no_task_id(
        self, repo: TaskHistoryRepository
    ) -> None:
        """Test write_artifact with missing task_id returns error."""
        result = json.loads(
            handle_write_artifact(
                repo, task_id=None, title="T", content="C", fmt="text"
            )
        )
        assert "error" in result

    def test_handle_write_artifact_invalid_format(
        self, repo: TaskHistoryRepository
    ) -> None:
        """Test write_artifact with invalid format returns error."""
        task = make_task()
        repo.create(task)

        result = json.loads(
            handle_write_artifact(
                repo,
                task_id="abcd1234",
                title="T",
                content="C",
                fmt="invalid",
            )
        )
        assert "error" in result
        assert "invalid" in result["error"].lower() or "Invalid" in result["error"]

    def test_handle_load_artifact(self, repo: TaskHistoryRepository) -> None:
        """Test loading an artifact via MCP handler."""
        task = make_task()
        repo.create(task)

        created = repo.create_artifact(
            task_id="abcd1234", title="Doc", content="Hello", fmt="markdown"
        )

        result = json.loads(handle_load_artifact(repo, created.id))
        assert result["id"] == created.id
        assert result["title"] == "Doc"
        assert result["content"] == "Hello"
        assert result["format"] == "markdown"

    def test_handle_load_artifact_not_found(self, repo: TaskHistoryRepository) -> None:
        """Test loading nonexistent artifact returns error."""
        result = json.loads(handle_load_artifact(repo, "nonexistent"))
        assert "error" in result

    def test_handle_list_artifacts_by_task(self, repo: TaskHistoryRepository) -> None:
        """Test listing artifacts for a specific task."""
        task = make_task()
        repo.create(task)

        repo.create_artifact(task_id="abcd1234", title="A1", content="C1", fmt="text")
        repo.create_artifact(task_id="abcd1234", title="A2", content="C2", fmt="text")

        result = json.loads(
            handle_list_artifacts(repo, process_id="proc5678", task_id="abcd1234")
        )
        assert len(result["artifacts"]) == 2
        # Content should NOT be included in list
        for item in result["artifacts"]:
            assert "content" not in item
            assert "title" in item
            assert "id" in item

    def test_handle_list_artifacts_by_process(
        self, repo: TaskHistoryRepository
    ) -> None:
        """Test listing artifacts for a whole process."""
        task1 = make_task(task_id="t1", process_id="proc1111", executor_id=1)
        task2 = make_task(task_id="t2", process_id="proc1111", executor_id=2)
        repo.create(task1)
        repo.create(task2)

        repo.create_artifact(task_id="t1", title="A1", content="C1", fmt="text")
        repo.create_artifact(task_id="t2", title="A2", content="C2", fmt="text")

        result = json.loads(handle_list_artifacts(repo, process_id="proc1111"))
        assert len(result["artifacts"]) == 2


class TestMCPTemplateHandlers:
    """Tests for MCP tool handler functions for templates."""

    def test_handle_list_artifact_templates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test listing available templates."""
        # Point global path to package defaults so templates are discovered
        monkeypatch.setattr(
            "wiggy.mcp.tools.get_all_templates",
            lambda: {
                name: tmpl
                for name, tmpl in (
                    (d.name, load_template_from_dir(d))
                    for d in get_package_templates_path().iterdir()
                    if d.is_dir() and (d / "template.yaml").exists()
                )
                if tmpl is not None
            },
        )
        result = json.loads(handle_list_artifact_templates())
        assert "templates" in result
        names = {t["name"] for t in result["templates"]}
        assert "prd" in names
        assert "documentation" in names

    def test_handle_load_artifact_template(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test loading a specific template."""
        pkg_path = get_package_templates_path()
        monkeypatch.setattr(
            "wiggy.mcp.tools.get_template_by_name",
            lambda name: load_template_from_dir(pkg_path / name),
        )
        result = json.loads(handle_load_artifact_template("prd"))
        assert result["name"] == "prd"
        assert result["format"] == "markdown"
        assert len(result["content"]) > 0
        assert "tags" in result

    def test_handle_load_artifact_template_not_found(self) -> None:
        """Test loading nonexistent template returns error."""
        result = json.loads(handle_load_artifact_template("nonexistent"))
        assert "error" in result


class TestValidFormats:
    """Test VALID_FORMATS constant."""

    def test_valid_formats(self) -> None:
        """Test that all expected formats are present."""
        assert VALID_FORMATS == {"json", "markdown", "xml", "text"}
