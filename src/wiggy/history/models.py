"""Task history data models."""

from dataclasses import dataclass, replace
from pathlib import Path
from sqlite3 import Row
from typing import Any, Self


@dataclass(frozen=True)
class TaskLog:
    """Immutable record of a task execution."""

    task_id: str  # 8 hex chars (wiggy-generated)
    process_id: str  # 8 hex chars, groups parallel executors
    executor_id: int

    created_at: str  # ISO8601 UTC
    branch: str  # e.g., "wiggy/a1b2c3d4"
    worktree: str  # Absolute path
    main_repo: str  # Absolute path
    engine: str

    # Optional fields
    finished_at: str | None = None
    failed_at: str | None = None
    model: str | None = None
    session_id: str | None = None  # Engine session (e.g., Claude's session_id)
    task_name: str | None = None
    prompt: str | None = None
    prompt_hash: str | None = None
    total_cost: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: int | None = None
    success: bool | None = None
    exit_code: int | None = None
    error_message: str | None = None
    parent_id: str | None = None

    @property
    def log_path(self) -> Path:
        """Return the path to this task's log file."""
        return Path(".wiggy") / "logs" / f"{self.task_id}.log"

    def with_completion(
        self,
        *,
        finished_at: str | None = None,
        failed_at: str | None = None,
        success: bool | None = None,
        exit_code: int | None = None,
        error_message: str | None = None,
        total_cost: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        duration_ms: int | None = None,
        session_id: str | None = None,
    ) -> Self:
        """Return a new TaskLog with completion fields updated."""
        updates: dict[str, Any] = {}
        if finished_at is not None:
            updates["finished_at"] = finished_at
        if failed_at is not None:
            updates["failed_at"] = failed_at
        if success is not None:
            updates["success"] = success
        if exit_code is not None:
            updates["exit_code"] = exit_code
        if error_message is not None:
            updates["error_message"] = error_message
        if total_cost is not None:
            updates["total_cost"] = total_cost
        if input_tokens is not None:
            updates["input_tokens"] = input_tokens
        if output_tokens is not None:
            updates["output_tokens"] = output_tokens
        if duration_ms is not None:
            updates["duration_ms"] = duration_ms
        if session_id is not None:
            updates["session_id"] = session_id
        return replace(self, **updates)

    @classmethod
    def from_row(cls, row: Row) -> Self:
        """Create a TaskLog from a database row."""
        return cls(
            task_id=row["task_id"],
            process_id=row["process_id"],
            executor_id=row["executor_id"],
            created_at=row["created_at"],
            finished_at=row["finished_at"],
            failed_at=row["failed_at"],
            branch=row["branch"],
            worktree=row["worktree"],
            main_repo=row["main_repo"],
            engine=row["engine"],
            model=row["model"],
            session_id=row["session_id"],
            task_name=row["task_name"],
            prompt=row["prompt"],
            prompt_hash=row["prompt_hash"],
            total_cost=row["total_cost"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            duration_ms=row["duration_ms"],
            success=bool(row["success"]) if row["success"] is not None else None,
            exit_code=row["exit_code"],
            error_message=row["error_message"],
            parent_id=row["parent_id"],
        )
