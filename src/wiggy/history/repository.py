"""Task history repository for database operations."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from wiggy.history.models import TaskLog
from wiggy.history.schema import migrate_if_needed


class TaskNotFoundError(Exception):
    """Raised when a task cannot be found by the specified lookup."""

    def __init__(self, lookup_type: str, value: str) -> None:
        self.lookup_type = lookup_type
        self.value = value
        super().__init__(f"Task not found by {lookup_type}: {value}")


class TaskHistoryRepository:
    """Repository for task history operations."""

    def __init__(self, db_path: Path | None = None) -> None:
        """Initialize the repository.

        Args:
            db_path: Path to the SQLite database. Defaults to .wiggy/history.db
        """
        if db_path is None:
            db_path = Path.cwd() / ".wiggy" / "history.db"
        self.db_path = db_path
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Ensure the database exists and schema is up to date."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            migrate_if_needed(conn)

    def _connect(self) -> sqlite3.Connection:
        """Create a database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # CRUD operations

    def create(self, task: TaskLog) -> TaskLog:
        """Insert a new task record.

        Returns the task as-is (no auto-generated fields).
        """
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO task_log (
                    task_id, process_id, executor_id, created_at, finished_at,
                    failed_at, branch, worktree, main_repo, engine, model,
                    session_id, task_name, prompt, prompt_hash, total_cost,
                    input_tokens, output_tokens, duration_ms, success,
                    exit_code, error_message, parent_id
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    task.task_id,
                    task.process_id,
                    task.executor_id,
                    task.created_at,
                    task.finished_at,
                    task.failed_at,
                    task.branch,
                    task.worktree,
                    task.main_repo,
                    task.engine,
                    task.model,
                    task.session_id,
                    task.task_name,
                    task.prompt,
                    task.prompt_hash,
                    task.total_cost,
                    task.input_tokens,
                    task.output_tokens,
                    task.duration_ms,
                    1 if task.success else (0 if task.success is False else None),
                    task.exit_code,
                    task.error_message,
                    task.parent_id,
                ),
            )
            conn.commit()
        return task

    def complete(
        self,
        task_id: str,
        *,
        success: bool,
        exit_code: int,
        finished_at: str | None = None,
        failed_at: str | None = None,
        total_cost: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        duration_ms: int | None = None,
        error_message: str | None = None,
    ) -> TaskLog:
        """Mark a task as completed with final metrics.

        Returns the updated TaskLog.
        """
        if finished_at is None:
            finished_at = datetime.now(UTC).isoformat()
        if not success and failed_at is None:
            failed_at = finished_at

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE task_log SET
                    finished_at = ?,
                    failed_at = ?,
                    success = ?,
                    exit_code = ?,
                    total_cost = ?,
                    input_tokens = ?,
                    output_tokens = ?,
                    duration_ms = ?,
                    error_message = ?
                WHERE task_id = ?
                """,
                (
                    finished_at,
                    failed_at,
                    1 if success else 0,
                    exit_code,
                    total_cost,
                    input_tokens,
                    output_tokens,
                    duration_ms,
                    error_message,
                    task_id,
                ),
            )
            conn.commit()

        task = self.get_by_task_id(task_id)
        if task is None:
            raise TaskNotFoundError("task_id", task_id)
        return task

    def update_session_id(self, task_id: str, session_id: str) -> None:
        """Update the session_id for a task (e.g., when received from Claude)."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE task_log SET session_id = ? WHERE task_id = ?",
                (session_id, task_id),
            )
            conn.commit()

    def add_ref(self, task_id: str, commit_hash: str) -> None:
        """Add a commit reference for a task."""
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO task_refs (task_id, commit_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (task_id, commit_hash, created_at),
            )
            conn.commit()

    def get_refs(self, task_id: str) -> list[str]:
        """Get all commit hashes for a task."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT commit_hash FROM task_refs "
                "WHERE task_id = ? ORDER BY created_at",
                (task_id,),
            )
            return [row["commit_hash"] for row in cursor.fetchall()]

    # Lookup operations (return Optional, don't raise)

    def get_by_task_id(self, task_id: str) -> TaskLog | None:
        """Get a task by its task_id."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM task_log WHERE task_id = ?", (task_id,)
            )
            row = cursor.fetchone()
            return TaskLog.from_row(row) if row else None

    def get_by_session_id(self, session_id: str) -> TaskLog | None:
        """Get a task by its engine session_id (e.g., Claude's session)."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM task_log WHERE session_id = ?", (session_id,)
            )
            row = cursor.fetchone()
            return TaskLog.from_row(row) if row else None

    def get_by_process_id(self, process_id: str) -> list[TaskLog]:
        """Get all tasks for a process (parallel execution group)."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM task_log WHERE process_id = ? ORDER BY executor_id",
                (process_id,),
            )
            return [TaskLog.from_row(row) for row in cursor.fetchall()]

    def get_by_branch(self, branch: str) -> TaskLog | None:
        """Get the most recent task for a branch."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM task_log WHERE branch = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (branch,),
            )
            row = cursor.fetchone()
            return TaskLog.from_row(row) if row else None

    def get_by_worktree(self, worktree: Path) -> TaskLog | None:
        """Get the most recent task for a worktree path."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM task_log WHERE worktree = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (str(worktree),),
            )
            row = cursor.fetchone()
            return TaskLog.from_row(row) if row else None

    def get_recent(self, limit: int = 10) -> list[TaskLog]:
        """Get the most recent tasks."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM task_log ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            return [TaskLog.from_row(row) for row in cursor.fetchall()]

    # Strict lookup operations (raise TaskNotFoundError)

    def require_by_task_id(self, task_id: str) -> TaskLog:
        """Get a task by task_id, raising if not found."""
        task = self.get_by_task_id(task_id)
        if task is None:
            raise TaskNotFoundError("task_id", task_id)
        return task

    def require_by_session_id(self, session_id: str) -> TaskLog:
        """Get a task by session_id, raising if not found."""
        task = self.get_by_session_id(session_id)
        if task is None:
            raise TaskNotFoundError("session_id", session_id)
        return task

    def require_by_branch(self, branch: str) -> TaskLog:
        """Get a task by branch, raising if not found."""
        task = self.get_by_branch(branch)
        if task is None:
            raise TaskNotFoundError("branch", branch)
        return task

    # Cleanup operations

    def get_tasks_older_than(self, days: int) -> list[TaskLog]:
        """Get all tasks older than the specified number of days."""
        cutoff = datetime.now(UTC)
        # Calculate cutoff date
        from datetime import timedelta

        cutoff_date = (cutoff - timedelta(days=days)).isoformat()

        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM task_log WHERE created_at < ? ORDER BY created_at",
                (cutoff_date,),
            )
            return [TaskLog.from_row(row) for row in cursor.fetchall()]

    def delete_task(self, task_id: str) -> bool:
        """Delete a task and its refs. Returns True if deleted."""
        with self._connect() as conn:
            # Refs are deleted by ON DELETE CASCADE
            cursor = conn.execute(
                "DELETE FROM task_log WHERE task_id = ?", (task_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
