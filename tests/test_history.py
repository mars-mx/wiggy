"""Tests for task history module."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from wiggy.history import (
    TaskHistoryRepository,
    TaskLog,
    TaskNotFoundError,
    cleanup_old_tasks,
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
    created_at: str | None = None,
    **kwargs: object,
) -> TaskLog:
    """Create a TaskLog for testing."""
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()
    defaults = {
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
        created_at=created_at,
        **defaults,  # type: ignore[arg-type]
    )


class TestTaskLog:
    """Tests for TaskLog dataclass."""

    def test_create_task_log(self) -> None:
        """Test creating a TaskLog."""
        task = make_task()
        assert task.task_id == "abcd1234"
        assert task.process_id == "proc5678"
        assert task.executor_id == 1
        assert task.branch == "wiggy/test"
        assert task.engine == "claude"

    def test_log_path(self) -> None:
        """Test log_path property."""
        task = make_task(task_id="deadbeef")
        assert task.log_path == Path(".wiggy/logs/deadbeef.log")

    def test_with_completion(self) -> None:
        """Test with_completion creates new TaskLog with updates."""
        task = make_task()
        completed = task.with_completion(
            finished_at="2024-01-01T12:00:00Z",
            success=True,
            exit_code=0,
            total_cost=0.05,
        )
        # Original unchanged
        assert task.finished_at is None
        assert task.success is None
        # New has updates
        assert completed.finished_at == "2024-01-01T12:00:00Z"
        assert completed.success is True
        assert completed.exit_code == 0
        assert completed.total_cost == 0.05
        # Preserved fields
        assert completed.task_id == task.task_id
        assert completed.engine == task.engine


class TestTaskHistoryRepository:
    """Tests for TaskHistoryRepository."""

    def test_create_and_retrieve(self, repo: TaskHistoryRepository) -> None:
        """Test creating and retrieving a task."""
        task = make_task()
        repo.create(task)

        retrieved = repo.get_by_task_id("abcd1234")
        assert retrieved is not None
        assert retrieved.task_id == "abcd1234"
        assert retrieved.branch == "wiggy/test"

    def test_get_by_task_id_not_found(self, repo: TaskHistoryRepository) -> None:
        """Test get_by_task_id returns None when not found."""
        result = repo.get_by_task_id("nonexistent")
        assert result is None

    def test_require_by_task_id_raises(self, repo: TaskHistoryRepository) -> None:
        """Test require_by_task_id raises when not found."""
        with pytest.raises(TaskNotFoundError) as exc:
            repo.require_by_task_id("nonexistent")
        assert exc.value.lookup_type == "task_id"
        assert exc.value.value == "nonexistent"

    def test_get_by_session_id(self, repo: TaskHistoryRepository) -> None:
        """Test retrieving by session_id."""
        task = make_task(session_id="sess_abc123")
        repo.create(task)

        retrieved = repo.get_by_session_id("sess_abc123")
        assert retrieved is not None
        assert retrieved.task_id == "abcd1234"

    def test_get_by_session_id_not_found(self, repo: TaskHistoryRepository) -> None:
        """Test get_by_session_id returns None when not found."""
        result = repo.get_by_session_id("nonexistent")
        assert result is None

    def test_require_by_session_id_raises(self, repo: TaskHistoryRepository) -> None:
        """Test require_by_session_id raises when not found."""
        with pytest.raises(TaskNotFoundError) as exc:
            repo.require_by_session_id("nonexistent")
        assert exc.value.lookup_type == "session_id"

    def test_get_by_process_id(self, repo: TaskHistoryRepository) -> None:
        """Test retrieving multiple tasks by process_id."""
        task1 = make_task(task_id="task0001", process_id="proc1111", executor_id=1)
        task2 = make_task(task_id="task0002", process_id="proc1111", executor_id=2)
        repo.create(task1)
        repo.create(task2)

        tasks = repo.get_by_process_id("proc1111")
        assert len(tasks) == 2
        assert tasks[0].executor_id == 1
        assert tasks[1].executor_id == 2

    def test_get_by_branch(self, repo: TaskHistoryRepository) -> None:
        """Test retrieving by branch."""
        task = make_task(branch="wiggy/feature123")
        repo.create(task)

        retrieved = repo.get_by_branch("wiggy/feature123")
        assert retrieved is not None
        assert retrieved.task_id == "abcd1234"

    def test_get_by_branch_not_found(self, repo: TaskHistoryRepository) -> None:
        """Test get_by_branch returns None when not found."""
        result = repo.get_by_branch("nonexistent")
        assert result is None

    def test_require_by_branch_raises(self, repo: TaskHistoryRepository) -> None:
        """Test require_by_branch raises when not found."""
        with pytest.raises(TaskNotFoundError) as exc:
            repo.require_by_branch("nonexistent")
        assert exc.value.lookup_type == "branch"

    def test_get_by_worktree(self, repo: TaskHistoryRepository) -> None:
        """Test retrieving by worktree path."""
        task = make_task(worktree="/tmp/my-worktree")
        repo.create(task)

        retrieved = repo.get_by_worktree(Path("/tmp/my-worktree"))
        assert retrieved is not None
        assert retrieved.task_id == "abcd1234"

    def test_get_recent(self, repo: TaskHistoryRepository) -> None:
        """Test getting recent tasks."""
        for i in range(5):
            task = make_task(
                task_id=f"task{i:04d}",
                created_at=(
                    datetime.now(timezone.utc) + timedelta(seconds=i)
                ).isoformat(),
            )
            repo.create(task)

        recent = repo.get_recent(limit=3)
        assert len(recent) == 3
        # Most recent first
        assert recent[0].task_id == "task0004"
        assert recent[1].task_id == "task0003"
        assert recent[2].task_id == "task0002"

    def test_complete(self, repo: TaskHistoryRepository) -> None:
        """Test completing a task."""
        task = make_task()
        repo.create(task)

        completed = repo.complete(
            "abcd1234",
            success=True,
            exit_code=0,
            total_cost=0.10,
            input_tokens=1000,
            output_tokens=500,
        )
        assert completed.success is True
        assert completed.exit_code == 0
        assert completed.total_cost == 0.10
        assert completed.finished_at is not None

    def test_complete_failure(self, repo: TaskHistoryRepository) -> None:
        """Test completing a failed task sets failed_at."""
        task = make_task()
        repo.create(task)

        completed = repo.complete(
            "abcd1234",
            success=False,
            exit_code=1,
            error_message="Something went wrong",
        )
        assert completed.success is False
        assert completed.exit_code == 1
        assert completed.failed_at is not None
        assert completed.error_message == "Something went wrong"

    def test_update_session_id(self, repo: TaskHistoryRepository) -> None:
        """Test updating session_id."""
        task = make_task()
        repo.create(task)

        repo.update_session_id("abcd1234", "sess_new123")

        retrieved = repo.get_by_task_id("abcd1234")
        assert retrieved is not None
        assert retrieved.session_id == "sess_new123"

    def test_add_and_get_refs(self, repo: TaskHistoryRepository) -> None:
        """Test adding and retrieving commit refs."""
        task = make_task()
        repo.create(task)

        repo.add_ref("abcd1234", "deadbeef1234")
        repo.add_ref("abcd1234", "cafebabe5678")

        refs = repo.get_refs("abcd1234")
        assert len(refs) == 2
        assert "deadbeef1234" in refs
        assert "cafebabe5678" in refs

    def test_add_ref_duplicate_ignored(self, repo: TaskHistoryRepository) -> None:
        """Test that adding duplicate ref is ignored."""
        task = make_task()
        repo.create(task)

        repo.add_ref("abcd1234", "deadbeef1234")
        repo.add_ref("abcd1234", "deadbeef1234")  # Duplicate

        refs = repo.get_refs("abcd1234")
        assert len(refs) == 1

    def test_delete_task(self, repo: TaskHistoryRepository) -> None:
        """Test deleting a task."""
        task = make_task()
        repo.create(task)
        repo.add_ref("abcd1234", "commit123")

        assert repo.delete_task("abcd1234") is True
        assert repo.get_by_task_id("abcd1234") is None
        # Refs should be cascade deleted
        assert repo.get_refs("abcd1234") == []

    def test_delete_nonexistent_task(self, repo: TaskHistoryRepository) -> None:
        """Test deleting nonexistent task returns False."""
        assert repo.delete_task("nonexistent") is False


class TestCleanup:
    """Tests for cleanup utilities."""

    def test_cleanup_old_tasks(self, repo: TaskHistoryRepository, tmp_path: Path) -> None:
        """Test cleaning up old tasks."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        new_date = datetime.now(timezone.utc).isoformat()

        old_task = make_task(task_id="oldtask1", created_at=old_date)
        new_task = make_task(task_id="newtask1", created_at=new_date)
        repo.create(old_task)
        repo.create(new_task)

        # Create a log file for old task
        log_dir = tmp_path / ".wiggy" / "logs"
        log_dir.mkdir(parents=True)
        log_file = log_dir / "oldtask1.log"
        log_file.write_text("test log")

        # Run cleanup with cwd as tmp_path
        import os

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            deleted = cleanup_old_tasks(repo, older_than_days=30)
        finally:
            os.chdir(original_cwd)

        assert deleted == ["oldtask1"]
        assert repo.get_by_task_id("oldtask1") is None
        assert repo.get_by_task_id("newtask1") is not None
        assert not log_file.exists()

    def test_cleanup_dry_run(self, repo: TaskHistoryRepository) -> None:
        """Test cleanup dry run doesn't delete."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        old_task = make_task(task_id="oldtask1", created_at=old_date)
        repo.create(old_task)

        deleted = cleanup_old_tasks(repo, older_than_days=30, dry_run=True)

        assert deleted == ["oldtask1"]
        # Task should still exist
        assert repo.get_by_task_id("oldtask1") is not None


class TestSchemaMigration:
    """Tests for schema migration."""

    def test_fresh_install_sets_version(self, temp_db: Path) -> None:
        """Test that fresh install sets schema version."""
        from wiggy.history.schema import get_schema_version, SCHEMA_VERSION

        repo = TaskHistoryRepository(db_path=temp_db)

        import sqlite3

        conn = sqlite3.connect(temp_db)
        version = get_schema_version(conn)
        conn.close()

        assert version == SCHEMA_VERSION

    def test_schema_is_idempotent(self, temp_db: Path) -> None:
        """Test that creating repo multiple times is safe."""
        repo1 = TaskHistoryRepository(db_path=temp_db)
        repo1.create(make_task(task_id="test1"))

        repo2 = TaskHistoryRepository(db_path=temp_db)
        # Should not error and task should still exist
        assert repo2.get_by_task_id("test1") is not None
