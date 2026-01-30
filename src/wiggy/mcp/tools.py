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
from wiggy.templates.loader import get_all_templates, get_template_by_name

logger = logging.getLogger(__name__)

VALID_FORMATS = {"json", "markdown", "xml", "text"}


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
        return json.dumps(
            {
                "error": f"Task '{task_id}' not found in task_log. "
                "The task may not have been registered before execution."
            }
        )

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


def handle_write_artifact(
    repo: TaskHistoryRepository,
    task_id: str | None,
    title: str,
    content: str,
    fmt: str,
    template_name: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Handle the write_artifact MCP tool call.

    Stores an artifact document in the database.

    Args:
        repo: The task history repository.
        task_id: The task ID from the X-Wiggy-Task-ID header.
        title: Artifact title.
        content: The artifact content body.
        fmt: Format string ('json', 'markdown', 'xml', 'text').
        template_name: Optional name of the template used.
        tags: Optional categorization tags.

    Returns:
        JSON string with status, artifact_id, and title.
    """
    if not task_id:
        return json.dumps({"error": "Missing X-Wiggy-Task-ID header."})

    if fmt not in VALID_FORMATS:
        valid = ", ".join(sorted(VALID_FORMATS))
        return json.dumps({"error": f"Invalid format '{fmt}'. Must be one of: {valid}"})

    try:
        artifact = repo.create_artifact(
            task_id=task_id,
            title=title,
            content=content,
            fmt=fmt,
            template_name=template_name,
            tags=tags,
        )
    except sqlite3.IntegrityError:
        logger.error(
            "FK constraint failed for task_id=%s — no task_log record exists",
            task_id,
        )
        return json.dumps(
            {
                "error": f"Task '{task_id}' not found in task_log. "
                "The task may not have been registered before execution."
            }
        )

    response: dict[str, Any] = {
        "status": "ok",
        "artifact_id": artifact.id,
        "title": artifact.title,
    }
    return json.dumps(response)


def handle_load_artifact(
    repo: TaskHistoryRepository,
    artifact_id: str,
) -> str:
    """Handle the load_artifact MCP tool call.

    Loads the full artifact content by ID.

    Args:
        repo: The task history repository.
        artifact_id: The artifact ID to load.

    Returns:
        JSON string with the full artifact or an error.
    """
    artifact = repo.get_artifact_by_id(artifact_id)
    if artifact is None:
        return json.dumps({"error": f"Artifact '{artifact_id}' not found."})

    response: dict[str, Any] = {
        "id": artifact.id,
        "task_id": artifact.task_id,
        "title": artifact.title,
        "content": artifact.content,
        "format": artifact.format,
        "template_name": artifact.template_name,
        "tags": list(artifact.tags),
        "created_at": artifact.created_at,
    }
    return json.dumps(response)


def handle_list_artifacts(
    repo: TaskHistoryRepository,
    process_id: str,
    task_id: str | None = None,
) -> str:
    """Handle the list_artifacts MCP tool call.

    Lists artifact metadata (without content) for a task or process.

    Args:
        repo: The task history repository.
        process_id: The current process ID.
        task_id: Optional task ID to filter by.

    Returns:
        JSON string with list of artifact metadata.
    """
    if task_id:
        artifacts = repo.get_artifacts_by_task_id(task_id)
    else:
        artifacts = repo.get_artifacts_by_process_id(process_id)

    items: list[dict[str, Any]] = []
    for a in artifacts:
        items.append(
            {
                "id": a.id,
                "task_id": a.task_id,
                "title": a.title,
                "format": a.format,
                "template_name": a.template_name,
                "tags": list(a.tags),
                "created_at": a.created_at,
            }
        )

    return json.dumps({"artifacts": items})


def handle_list_artifact_templates() -> str:
    """Handle the list_artifact_templates MCP tool call.

    Lists available artifact templates (name, description, format).

    Returns:
        JSON string with list of template metadata.
    """
    templates = get_all_templates()

    items: list[dict[str, Any]] = []
    for _name, tmpl in sorted(templates.items()):
        items.append(
            {
                "name": tmpl.name,
                "description": tmpl.description,
                "format": tmpl.format,
                "tags": list(tmpl.tags),
            }
        )

    return json.dumps({"templates": items})


def handle_load_artifact_template(
    template_name: str,
) -> str:
    """Handle the load_artifact_template MCP tool call.

    Loads a full artifact template including content.

    Args:
        template_name: Name of the template to load.

    Returns:
        JSON string with full template or an error.
    """
    tmpl = get_template_by_name(template_name)
    if tmpl is None:
        return json.dumps({"error": f"Template '{template_name}' not found."})

    response: dict[str, Any] = {
        "name": tmpl.name,
        "description": tmpl.description,
        "format": tmpl.format,
        "content": tmpl.content,
        "tags": list(tmpl.tags),
    }
    return json.dumps(response)


def handle_write_knowledge(
    repo: TaskHistoryRepository,
    key: str,
    content: str,
    reason: str,
) -> str:
    """Handle the write_knowledge MCP tool call.

    Writes a new version of a knowledge entry.

    Args:
        repo: The task history repository.
        key: The knowledge key (e.g. 'api-design-decisions').
        content: The knowledge content.
        reason: Why this version was created.

    Returns:
        JSON string with status, key, version, and created_at.
    """
    knowledge = repo.write_knowledge(key, content, reason)
    response: dict[str, Any] = {
        "status": "ok",
        "key": knowledge.key,
        "version": knowledge.version,
        "created_at": knowledge.created_at,
    }
    return json.dumps(response)


def handle_get_knowledge(
    repo: TaskHistoryRepository,
    key: str,
    version: int | None = None,
) -> str:
    """Handle the get_knowledge MCP tool call.

    Gets a knowledge entry by key, optionally at a specific version.

    Args:
        repo: The task history repository.
        key: The knowledge key to look up.
        version: Optional version number. Defaults to latest.

    Returns:
        JSON string with the knowledge entry or an error.
    """
    knowledge = repo.get_knowledge(key, version)
    if knowledge is None:
        lookup = f"{key} v{version}" if version else key
        return json.dumps({"error": f"Knowledge entry '{lookup}' not found."})

    response: dict[str, Any] = {
        "key": knowledge.key,
        "version": knowledge.version,
        "content": knowledge.content,
        "reason": knowledge.reason,
        "created_at": knowledge.created_at,
    }
    return json.dumps(response)


def handle_view_knowledge_history(
    repo: TaskHistoryRepository,
    key: str,
) -> str:
    """Handle the view_knowledge_history MCP tool call.

    Lists all versions of a knowledge entry.

    Args:
        repo: The task history repository.
        key: The knowledge key to look up.

    Returns:
        JSON string with the key and list of versions.
    """
    entries = repo.get_knowledge_history(key)
    versions: list[dict[str, Any]] = []
    for entry in entries:
        versions.append(
            {
                "version": entry.version,
                "reason": entry.reason,
                "created_at": entry.created_at,
                "content_preview": entry.content[:200],
            }
        )

    return json.dumps({"key": key, "versions": versions})


def handle_search_knowledge(
    repo: TaskHistoryRepository,
    query: str,
    page: int = 1,
) -> str:
    """Handle the search_knowledge MCP tool call.

    Searches knowledge, results, and artifacts by semantic similarity.

    Args:
        repo: The task history repository.
        query: The search query.
        page: Page number (1-based). Defaults to 1.

    Returns:
        JSON string with query, page, results, and has_more flag.
    """
    page_size = 10
    results = repo.search_similar(query, page, page_size)

    items: list[dict[str, Any]] = []
    for r in results:
        items.append(
            {
                "source": r.source,
                "source_id": r.source_id,
                "title": r.title,
                "snippet": r.snippet,
                "distance": r.distance,
                "created_at": r.created_at,
            }
        )

    response: dict[str, Any] = {
        "query": query,
        "page": page,
        "results": items,
        "has_more": len(results) == page_size,
    }
    return json.dumps(response)
