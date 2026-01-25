"""Retention policy utilities for task history cleanup."""

from pathlib import Path

from wiggy.history.repository import TaskHistoryRepository


def cleanup_old_tasks(
    repo: TaskHistoryRepository,
    older_than_days: int = 30,
    dry_run: bool = False,
) -> list[str]:
    """Delete tasks and logs older than threshold.

    Args:
        repo: The task history repository.
        older_than_days: Delete tasks older than this many days.
        dry_run: If True, don't actually delete, just return what would be deleted.

    Returns:
        List of deleted (or would-be-deleted) task_ids.
    """
    old_tasks = repo.get_tasks_older_than(older_than_days)
    deleted_ids: list[str] = []

    for task in old_tasks:
        task_id = task.task_id

        if dry_run:
            deleted_ids.append(task_id)
            continue

        # Delete log file if it exists
        log_path = Path.cwd() / task.log_path
        if log_path.exists():
            log_path.unlink()

        # Delete from database
        if repo.delete_task(task_id):
            deleted_ids.append(task_id)

    return deleted_ids
