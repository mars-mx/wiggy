"""Task history repository for database operations."""

from __future__ import annotations

import json
import sqlite3
import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from wiggy.history.embeddings import EmbeddingProvider, get_provider
from wiggy.history.models import Artifact, Knowledge, SearchResult, TaskLog, TaskResult

if TYPE_CHECKING:
    from wiggy.processes.base import OrchestratorDecision
from wiggy.history.schema import migrate_if_needed


def _serialize_vec(vector: list[float]) -> bytes:
    """Serialize a float vector to bytes for sqlite-vec storage."""
    return struct.pack(f"{len(vector)}f", *vector)


class TaskNotFoundError(Exception):
    """Raised when a task cannot be found by the specified lookup."""

    def __init__(self, lookup_type: str, value: str) -> None:
        self.lookup_type = lookup_type
        self.value = value
        super().__init__(f"Task not found by {lookup_type}: {value}")


class TaskHistoryRepository:
    """Repository for task history operations."""

    def __init__(
        self,
        db_path: Path | None = None,
        embedding_provider: str = "fastembed",
        embedding_model: str | None = None,
    ) -> None:
        """Initialize the repository.

        Args:
            db_path: Path to the SQLite database. Defaults to .wiggy/history.db
            embedding_provider: Name of the embedding provider to use.
            embedding_model: Optional model override for the provider.
        """
        if db_path is None:
            db_path = Path.cwd() / ".wiggy" / "history.db"
        self.db_path = db_path
        self._embedding_provider = embedding_provider
        self._embedding_model = embedding_model
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Ensure the database exists and schema is up to date."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            migrate_if_needed(conn)

    def _connect(self) -> sqlite3.Connection:
        """Create a database connection with row factory and sqlite-vec."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        import sqlite_vec

        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
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
                    exit_code, error_message, parent_id, is_orchestrator
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
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
                    1 if task.is_orchestrator else 0,
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

    # Task result operations

    def create_result(
        self,
        task_id: str,
        result_text: str,
        key_files: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Insert a task result. Uses UPSERT to allow overwriting.

        key_files and tags are JSON-serialized for storage.
        created_at is set to now (UTC).
        """
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO task_result (
                    task_id, result_text, key_files, tags,
                    has_summary, created_at
                ) VALUES (?, ?, ?, ?, 0, ?)
                """,
                (
                    task_id,
                    result_text,
                    json.dumps(key_files or []),
                    json.dumps(tags or []),
                    created_at,
                ),
            )
            conn.commit()
        self._embed_result(task_id, result_text)

    def update_summary(self, task_id: str, summary_text: str) -> None:
        """Store the compressed summary and set has_summary = 1."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE task_result
                SET summary_text = ?, has_summary = 1
                WHERE task_id = ?
                """,
                (summary_text, task_id),
            )
            conn.commit()

    def get_result_by_task_id(self, task_id: str) -> TaskResult | None:
        """Get result by task_id directly."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM task_result WHERE task_id = ?", (task_id,)
            )
            row = cursor.fetchone()
            return TaskResult.from_row(row) if row else None

    def get_result_by_task_name(
        self, task_name: str, process_id: str
    ) -> TaskResult | None:
        """Get most recent result for a task name within a process.

        Joins task_result with task_log to resolve task_name → task_id.
        Falls back to most recent result globally (without process_id filter)
        if no match found within the process.
        """
        with self._connect() as conn:
            # Try within process first
            cursor = conn.execute(
                """
                SELECT tr.*
                FROM task_result tr
                JOIN task_log tl ON tr.task_id = tl.task_id
                WHERE tl.task_name = ? AND tl.process_id = ?
                ORDER BY tr.created_at DESC LIMIT 1
                """,
                (task_name, process_id),
            )
            row = cursor.fetchone()
            if row:
                return TaskResult.from_row(row)

            # Fallback: most recent globally
            cursor = conn.execute(
                """
                SELECT tr.*
                FROM task_result tr
                JOIN task_log tl ON tr.task_id = tl.task_id
                WHERE tl.task_name = ?
                ORDER BY tr.created_at DESC LIMIT 1
                """,
                (task_name,),
            )
            row = cursor.fetchone()
            return TaskResult.from_row(row) if row else None

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
            cursor = conn.execute("DELETE FROM task_log WHERE task_id = ?", (task_id,))
            conn.commit()
            return cursor.rowcount > 0

    # Artifact operations

    def create_artifact(
        self,
        task_id: str,
        title: str,
        content: str,
        fmt: str,
        template_name: str | None = None,
        tags: list[str] | None = None,
    ) -> Artifact:
        """Insert a new artifact record.

        Args:
            task_id: The task this artifact belongs to.
            title: Artifact title.
            content: The artifact content body.
            fmt: Format string ('json', 'markdown', 'xml', 'text').
            template_name: Optional name of the template used.
            tags: Optional categorization tags.

        Returns:
            The created Artifact.
        """
        import secrets

        artifact_id = secrets.token_hex(4)
        created_at = datetime.now(UTC).isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifact (
                    id, task_id, title, content, format,
                    template_name, tags, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    task_id,
                    title,
                    content,
                    fmt,
                    template_name,
                    json.dumps(tags or []),
                    created_at,
                ),
            )
            conn.commit()

        self._embed_artifact(artifact_id, content)

        return Artifact(
            id=artifact_id,
            task_id=task_id,
            title=title,
            content=content,
            format=fmt,
            tags=tuple(tags) if tags else (),
            created_at=created_at,
            template_name=template_name,
        )

    def get_artifact_by_id(self, artifact_id: str) -> Artifact | None:
        """Get an artifact by its ID."""
        with self._connect() as conn:
            cursor = conn.execute("SELECT * FROM artifact WHERE id = ?", (artifact_id,))
            row = cursor.fetchone()
            return Artifact.from_row(row) if row else None

    def get_artifacts_by_task_id(self, task_id: str) -> list[Artifact]:
        """Get all artifacts for a task."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM artifact WHERE task_id = ? ORDER BY created_at",
                (task_id,),
            )
            return [Artifact.from_row(row) for row in cursor.fetchall()]

    def get_artifacts_by_process_id(self, process_id: str) -> list[Artifact]:
        """Get all artifacts for all tasks in a process."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT a.*
                FROM artifact a
                JOIN task_log tl ON a.task_id = tl.task_id
                WHERE tl.process_id = ?
                ORDER BY a.created_at
                """,
                (process_id,),
            )
            return [Artifact.from_row(row) for row in cursor.fetchall()]

    # Knowledge CRUD operations

    def write_knowledge(self, key: str, content: str, reason: str) -> Knowledge:
        """Write a new version of a knowledge entry.

        Automatically increments the version number for the given key.
        """
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM knowledge WHERE key = ?",
                (key,),
            )
            next_version: int = cursor.fetchone()[0] + 1
            conn.execute(
                """
                INSERT INTO knowledge (key, version, content, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key, next_version, content, reason, created_at),
            )
            row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()

        self._embed_knowledge(row_id, content)

        return Knowledge(
            id=row_id,
            key=key,
            version=next_version,
            content=content,
            reason=reason,
            created_at=created_at,
        )

    def get_knowledge(self, key: str, version: int | None = None) -> Knowledge | None:
        """Get a knowledge entry by key, optionally at a specific version.

        If version is None, returns the latest version.
        """
        with self._connect() as conn:
            if version is None:
                cursor = conn.execute(
                    "SELECT * FROM knowledge WHERE key = ? "
                    "ORDER BY version DESC LIMIT 1",
                    (key,),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM knowledge WHERE key = ? AND version = ?",
                    (key, version),
                )
            row = cursor.fetchone()
            return Knowledge.from_row(row) if row else None

    def get_knowledge_history(self, key: str) -> list[Knowledge]:
        """Get all versions of a knowledge entry, ordered by version ascending."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM knowledge WHERE key = ? ORDER BY version ASC",
                (key,),
            )
            return [Knowledge.from_row(row) for row in cursor.fetchall()]

    # Orchestrator decision operations

    def save_orchestrator_decision(
        self, process_id: str, decision: OrchestratorDecision
    ) -> None:
        """Persist an orchestrator decision."""
        injected_json: str | None = None
        if decision.injected_steps:
            injected_json = json.dumps(
                [step.to_dict() for step in decision.injected_steps]
            )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orchestrator_decision (
                    process_id, task_id, phase, step_index,
                    decision, reasoning, injected_steps, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    process_id,
                    decision.task_id,
                    decision.phase,
                    decision.step_index,
                    decision.decision,
                    decision.reasoning,
                    injected_json,
                    decision.created_at,
                ),
            )
            conn.commit()

    def get_orchestrator_decisions(self, process_id: str) -> list[OrchestratorDecision]:
        """Get all orchestrator decisions for a process, ordered by creation time."""
        from wiggy.processes.base import OrchestratorDecision, ProcessStep

        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT * FROM orchestrator_decision WHERE process_id = ? "
                "ORDER BY created_at",
                (process_id,),
            )
            results: list[OrchestratorDecision] = []
            for row in cursor.fetchall():
                injected_raw = row["injected_steps"]
                injected: tuple[ProcessStep, ...] = ()
                if injected_raw:
                    injected = tuple(
                        ProcessStep.from_dict(s) for s in json.loads(injected_raw)
                    )
                results.append(
                    OrchestratorDecision(
                        phase=row["phase"],
                        step_index=row["step_index"],
                        decision=row["decision"],
                        reasoning=row["reasoning"],
                        injected_steps=injected,
                        task_id=row["task_id"],
                        created_at=row["created_at"],
                    )
                )
            return results

    def get_earliest_ref_for_process(self, process_id: str) -> str | None:
        """Get the earliest commit hash across all tasks in a process.

        Joins task_refs with task_log to find the first commit recorded
        for any task belonging to the given process.

        Returns:
            The commit hash string, or None if no refs exist.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT tr.commit_hash
                FROM task_refs tr
                JOIN task_log tl ON tr.task_id = tl.task_id
                WHERE tl.process_id = ?
                ORDER BY tr.created_at ASC
                LIMIT 1
                """,
                (process_id,),
            )
            row = cursor.fetchone()
            return row["commit_hash"] if row else None

    # Private embedding methods

    def _get_provider(self) -> EmbeddingProvider:
        """Get the embedding provider (lazily created)."""
        return get_provider(self._embedding_provider, self._embedding_model)

    def _embed_knowledge(self, knowledge_id: int, content: str) -> None:
        """Embed knowledge content and store in vec_knowledge."""
        vector = self._get_provider().embed_text(content)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO vec_knowledge (rowid, embedding) VALUES (?, ?)",
                (knowledge_id, _serialize_vec(vector)),
            )
            conn.commit()

    def _embed_result(self, task_id: str, content: str) -> None:
        """Embed result content and store in vec_results."""
        vector = self._get_provider().embed_text(content)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT rowid FROM task_result WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                return
            conn.execute(
                "INSERT OR REPLACE INTO vec_results (rowid, embedding)"
                " VALUES (?, ?)",
                (row[0], _serialize_vec(vector)),
            )
            conn.commit()

    def _embed_artifact(self, artifact_id: str, content: str) -> None:
        """Embed artifact content and store in vec_artifacts."""
        vector = self._get_provider().embed_text(content)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT rowid FROM artifact WHERE id = ?",
                (artifact_id,),
            ).fetchone()
            if row is None:
                return
            conn.execute(
                "INSERT OR REPLACE INTO vec_artifacts (rowid, embedding)"
                " VALUES (?, ?)",
                (row[0], _serialize_vec(vector)),
            )
            conn.commit()

    # Similarity search

    def search_similar(
        self, query: str, page: int = 1, page_size: int = 10
    ) -> list[SearchResult]:
        """Search across knowledge, results, and artifacts by semantic similarity.

        Returns results sorted by distance, paginated.
        """
        provider = self._get_provider()
        query_vec = _serialize_vec(provider.embed_text(query))
        limit = page * page_size  # fetch enough to paginate after merge

        results: list[SearchResult] = []

        with self._connect() as conn:
            # Search knowledge (deduplicate to latest version per key)
            cursor = conn.execute(
                """
                SELECT k.id, k.key, k.version, k.content, k.created_at, v.distance
                FROM vec_knowledge v
                JOIN knowledge k ON k.id = v.rowid
                WHERE v.embedding MATCH ? AND k = ?
                ORDER BY v.distance
                """,
                (query_vec, limit),
            )
            seen_keys: dict[str, SearchResult] = {}
            for row in cursor.fetchall():
                key = row["key"]
                if key not in seen_keys:
                    snippet = row["content"][:200]
                    seen_keys[key] = SearchResult(
                        source="knowledge",
                        source_id=str(row["id"]),
                        title=key,
                        snippet=snippet,
                        distance=row["distance"],
                        created_at=row["created_at"],
                    )
            results.extend(seen_keys.values())

            # Search results
            cursor = conn.execute(
                """
                SELECT tr.task_id, tr.result_text, tr.created_at, v.distance
                FROM vec_results v
                JOIN task_result tr ON tr.rowid = v.rowid
                WHERE v.embedding MATCH ? AND k = ?
                ORDER BY v.distance
                """,
                (query_vec, limit),
            )
            for row in cursor.fetchall():
                snippet = row["result_text"][:200]
                results.append(
                    SearchResult(
                        source="result",
                        source_id=row["task_id"],
                        title=f"Result for {row['task_id']}",
                        snippet=snippet,
                        distance=row["distance"],
                        created_at=row["created_at"],
                    )
                )

            # Search artifacts
            cursor = conn.execute(
                """
                SELECT a.id, a.title, a.content, a.created_at, v.distance
                FROM vec_artifacts v
                JOIN artifact a ON a.rowid = v.rowid
                WHERE v.embedding MATCH ? AND k = ?
                ORDER BY v.distance
                """,
                (query_vec, limit),
            )
            for row in cursor.fetchall():
                snippet = row["content"][:200]
                results.append(
                    SearchResult(
                        source="artifact",
                        source_id=row["id"],
                        title=row["title"],
                        snippet=snippet,
                        distance=row["distance"],
                        created_at=row["created_at"],
                    )
                )

        # Sort all results by distance and paginate
        results.sort(key=lambda r: r.distance)
        offset = (page - 1) * page_size
        return results[offset : offset + page_size]
