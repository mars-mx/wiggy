"""MCP tool handler implementations for the Wiggy server."""

import json
import logging
import sqlite3
from typing import Any

from wiggy.history.repository import TaskHistoryRepository
from wiggy.mcp.compression import (
    CompressionError,
    compress_result,
    is_compression_available,
)

logger = logging.getLogger(__name__)


def handle_write_result(
    repo: TaskHistoryRepository,
    task_id: str | None,
    result: str,
    key_files: list[str] | None = None,
    tags: list[str] | None = None,
) -> str:
    """Handle the write_result MCP tool call.

    Stores the result in the database and optionally compresses it.

    Args:
        repo: The task history repository.
        task_id: The task ID from the X-Wiggy-Task-ID header.
        result: The full result text.
        key_files: Optional list of relevant file paths.
        tags: Optional categorization tags.

    Returns:
        JSON string with status, task_id, and summary_preview.
    """
    if not task_id:
        return json.dumps({"error": "Missing X-Wiggy-Task-ID header."})

    try:
        repo.create_result(task_id, result, key_files or [], tags or [])
    except sqlite3.IntegrityError:
        logger.error(
            "FK constraint failed for task_id=%s — no task_log record exists",
            task_id,
        )
        return json.dumps({
            "error": f"Task '{task_id}' not found in task_log. "
            "The task may not have been registered before execution."
        })

    summary_preview = "Compression skipped"
    if is_compression_available():
        try:
            summary_text = compress_result(result)
            repo.update_summary(task_id, summary_text)
            summary_preview = summary_text[:200]
        except CompressionError as exc:
            logger.warning(
                "Compression failed for task %s: %s",
                task_id,
                exc,
            )

    response: dict[str, Any] = {
        "status": "ok",
        "task_id": task_id,
        "summary_preview": summary_preview,
    }
    return json.dumps(response)


def handle_load_result(
    repo: TaskHistoryRepository,
    process_id: str,
    task_name: str | None = None,
    task_id: str | None = None,
) -> str:
    """Handle the load_result MCP tool call.

    Loads the full result text for a task.

    Args:
        repo: The task history repository.
        process_id: The current process ID for task_name lookups.
        task_name: Name of the task to load (resolved via process_id).
        task_id: Specific task ID to load (overrides task_name).

    Returns:
        JSON string with the full result or an error.
    """
    if not task_name and not task_id:
        return json.dumps(
            {"error": "At least one of task_name or task_id must be provided."}
        )

    result = None
    if task_id:
        result = repo.get_result_by_task_id(task_id)
    elif task_name:
        result = repo.get_result_by_task_name(task_name, process_id)

    if result is None:
        lookup = task_id or task_name
        return json.dumps(
            {"error": f"No result found for task '{lookup}' in the current process."}
        )

    response: dict[str, Any] = {
        "result_text": result.result_text,
        "key_files": list(result.key_files),
        "tags": list(result.tags),
        "created_at": result.created_at,
    }
    return json.dumps(response)


def handle_read_result_summary(
    repo: TaskHistoryRepository,
    process_id: str,
    task_name: str | None = None,
    task_id: str | None = None,
) -> str:
    """Handle the read_result_summary MCP tool call.

    Loads the compressed summary for a task.

    Args:
        repo: The task history repository.
        process_id: The current process ID for task_name lookups.
        task_name: Name of the task to load (resolved via process_id).
        task_id: Specific task ID to load (overrides task_name).

    Returns:
        JSON string with the summary or an error.
    """
    if not task_name and not task_id:
        return json.dumps(
            {"error": "At least one of task_name or task_id must be provided."}
        )

    result = None
    if task_id:
        result = repo.get_result_by_task_id(task_id)
    elif task_name:
        result = repo.get_result_by_task_name(task_name, process_id)

    if result is None:
        lookup = task_id or task_name
        return json.dumps(
            {"error": f"No result found for task '{lookup}' in the current process."}
        )

    if not result.has_summary:
        name = task_name or task_id
        return json.dumps(
            {
                "error": f"No summary available for task '{name}'. "
                "The task may not have called write_result, or "
                "compression failed. Use load_result to access "
                "the raw output."
            }
        )

    response: dict[str, Any] = {
        "summary_text": result.summary_text,
        "key_files": list(result.key_files),
        "created_at": result.created_at,
    }
    return json.dumps(response)
