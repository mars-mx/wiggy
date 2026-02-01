"""MCP tool handler implementations for the Wiggy server."""

import json
import logging
import sqlite3
import subprocess
from datetime import UTC, datetime
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
VALID_DECISIONS = {"proceed", "inject", "abort"}
_MAX_DIFF_BYTES = 50 * 1024  # 50KB truncation limit for git diff output

# Tool scoping: "shared" tools are available to all callers;
# "orchestrator" tools are restricted to orchestrator tasks.
TOOL_SCOPES: dict[str, str] = {
    "write_result": "shared",
    "load_result": "shared",
    "read_result_summary": "shared",
    "write_artifact": "shared",
    "load_artifact": "shared",
    "list_artifacts": "shared",
    "list_artifact_templates": "shared",
    "load_artifact_template": "shared",
    "write_knowledge": "shared",
    "get_knowledge": "shared",
    "view_knowledge_history": "shared",
    "search_knowledge": "shared",
    "get_process_state": "orchestrator",
    "set_process_decision": "orchestrator",
    "inject_steps": "orchestrator",
    "get_git_diff": "orchestrator",
    "get_commit_log": "orchestrator",
}

ORCHESTRATOR_TOOL_NAMES: frozenset[str] = frozenset(
    name for name, scope in TOOL_SCOPES.items() if scope == "orchestrator"
)

# Shared in-memory state store keyed by process_id.
# The process runner (chunk 06) populates this with ProcessRun snapshots
# so that MCP tools can access process spec, current_index, etc.
_process_state_store: dict[str, dict[str, Any]] = {}


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


# ── Process state & decision tools ────────────────────────────────────


def handle_get_process_state(
    repo: TaskHistoryRepository,
    process_id: str,
) -> str:
    """Handle the get_process_state MCP tool call.

    Returns the full current process state including completed steps,
    pending steps, current index, and orchestrator decisions.

    Args:
        repo: The task history repository.
        process_id: The current process ID.

    Returns:
        JSON string with process state or an error.
    """
    tasks = repo.get_by_process_id(process_id)
    if not tasks:
        return json.dumps({"error": f"No tasks found for process '{process_id}'."})

    # Build completed steps from task_log records that have finished
    completed_steps: list[dict[str, Any]] = []
    for idx, task in enumerate(tasks):
        if task.finished_at is not None:
            completed_steps.append(
                {
                    "index": idx,
                    "task_name": task.task_name,
                    "task_id": task.task_id,
                    "success": task.success,
                    "exit_code": task.exit_code,
                    "duration_ms": task.duration_ms,
                }
            )

    # Get orchestrator decisions
    decisions = repo.get_orchestrator_decisions(process_id)
    decision_items: list[dict[str, Any]] = []
    for d in decisions:
        item: dict[str, Any] = {
            "phase": d.phase,
            "step_index": d.step_index,
            "decision": d.decision,
            "reasoning": d.reasoning,
            "task_id": d.task_id,
            "created_at": d.created_at,
        }
        if d.injected_steps:
            item["injected_steps"] = [s.to_dict() for s in d.injected_steps]
        decision_items.append(item)

    # Derive pending steps and current_index from state store if available
    state = _process_state_store.get(process_id)
    process_name = ""
    pending_steps: list[dict[str, Any]] = []
    current_index = len(completed_steps)

    if state:
        process_name = state.get("process_name", "")
        current_index = state.get("current_index", current_index)
        all_steps: list[dict[str, Any]] = state.get("steps", [])
        for idx, step in enumerate(all_steps):
            if idx >= current_index:
                pending_steps.append({"index": idx, "task_name": step.get("task", "")})

    response: dict[str, Any] = {
        "process_id": process_id,
        "process_name": process_name,
        "completed_steps": completed_steps,
        "pending_steps": pending_steps,
        "current_index": current_index,
        "orchestrator_decisions": decision_items,
    }
    return json.dumps(response)


def handle_set_process_decision(
    repo: TaskHistoryRepository,
    process_id: str,
    task_id: str | None,
    decision: str,
    reasoning: str,
    injected_steps: list[dict[str, str]] | None = None,
) -> str:
    """Handle the set_process_decision MCP tool call.

    Records the orchestrator's decision for the current phase.

    Args:
        repo: The task history repository.
        process_id: The current process ID.
        task_id: The orchestrator's task ID from X-Wiggy-Task-ID header.
        decision: One of "proceed", "inject", "abort".
        reasoning: Explanation of the decision.
        injected_steps: List of {task_name, prompt} dicts (required for "inject").

    Returns:
        JSON string with confirmation or an error.
    """
    if not task_id:
        return json.dumps({"error": "Missing X-Wiggy-Task-ID header."})

    if decision not in VALID_DECISIONS:
        valid = ", ".join(sorted(VALID_DECISIONS))
        return json.dumps(
            {"error": f"Invalid decision '{decision}'. Must be one of: {valid}"}
        )

    if decision == "inject" and not injected_steps:
        return json.dumps(
            {"error": "injected_steps is required when decision is 'inject'."}
        )

    if decision != "inject" and injected_steps:
        return json.dumps(
            {
                "error": "injected_steps must not be provided "
                "when decision is not 'inject'."
            }
        )

    # Lazy imports to avoid circular dependency (wiggy.processes -> wiggy.mcp)
    from wiggy.processes.base import OrchestratorDecision, ProcessStep

    # Convert injected_steps dicts to ProcessStep objects
    steps: tuple[ProcessStep, ...] = ()
    if injected_steps:
        steps = tuple(
            ProcessStep(task=s["task_name"], prompt=s.get("prompt"))
            for s in injected_steps
        )

    # Derive step_index from state store if available
    state = _process_state_store.get(process_id)
    step_index = state.get("current_index", 0) if state else 0

    decision_obj = OrchestratorDecision(
        phase="runtime",
        step_index=step_index,
        decision=decision,
        reasoning=reasoning,
        injected_steps=steps,
        task_id=task_id,
        created_at=datetime.now(UTC).isoformat(),
    )

    try:
        repo.save_orchestrator_decision(process_id, decision_obj)
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

    return json.dumps({"status": "ok", "decision": decision, "task_id": task_id})


def handle_inject_steps(
    repo: TaskHistoryRepository,
    task_id: str | None,
    process_id: str,
    steps: list[dict[str, str]],
) -> str:
    """Handle the inject_steps MCP tool call.

    Validates each step's task_name, converts to ProcessStep objects,
    and records an OrchestratorDecision with decision="inject".

    Args:
        repo: The task history repository.
        task_id: The orchestrator's task ID from X-Wiggy-Task-ID header.
        process_id: The current process ID.
        steps: List of dicts with 'task_name' and optional 'prompt'.

    Returns:
        JSON string with confirmation or an error.
    """
    if not task_id:
        return json.dumps({"error": "Missing X-Wiggy-Task-ID header."})

    if not steps:
        return json.dumps({"error": "steps must be a non-empty list."})

    # Lazy imports to avoid circular dependency
    from wiggy.processes.base import OrchestratorDecision, ProcessStep
    from wiggy.tasks import get_task_by_name

    # Validate each step's task_name
    process_steps: list[ProcessStep] = []
    for s in steps:
        task_name = s.get("task_name", "")
        if not task_name:
            return json.dumps({"error": "Each step must have a 'task_name'."})

        task_spec = get_task_by_name(task_name)
        if task_spec is None:
            return json.dumps(
                {"error": f"Unknown task: '{task_name}'. Check available tasks."}
            )

        process_steps.append(
            ProcessStep(task=task_name, prompt=s.get("prompt"))
        )

    # Derive step_index from state store if available
    state = _process_state_store.get(process_id)
    step_index = state.get("current_index", 0) if state else 0

    decision_obj = OrchestratorDecision(
        phase="inject_request",
        step_index=step_index,
        decision="inject",
        reasoning="Injected via inject_steps tool",
        injected_steps=tuple(process_steps),
        task_id=task_id,
        created_at=datetime.now(UTC).isoformat(),
    )

    try:
        repo.save_orchestrator_decision(process_id, decision_obj)
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

    return json.dumps({
        "status": "ok",
        "injected_count": len(process_steps),
        "steps": [s.get("task_name", "") for s in steps],
    })


# ── Git inspection tools ──────────────────────────────────────────────


def _resolve_worktree(
    repo: TaskHistoryRepository,
    task_id: str | None,
) -> str | None:
    """Look up the worktree path from the task_log for the given task_id."""
    if not task_id:
        return None
    task = repo.get_by_task_id(task_id)
    return task.worktree if task else None


def _resolve_since_commit(
    repo: TaskHistoryRepository,
    process_id: str,
    since_commit: str | None,
) -> str | None:
    """Resolve the since_commit reference.

    If since_commit is provided, return it. Otherwise look up the earliest
    commit ref for the process.
    """
    if since_commit:
        return since_commit
    return repo.get_earliest_ref_for_process(process_id)


def handle_get_git_diff(
    repo: TaskHistoryRepository,
    task_id: str | None,
    process_id: str,
    since_commit: str | None = None,
) -> str:
    """Handle the get_git_diff MCP tool call.

    Returns the git diff for the process worktree.

    Args:
        repo: The task history repository.
        task_id: The task ID from X-Wiggy-Task-ID header (for worktree lookup).
        process_id: The current process ID (for earliest commit lookup).
        since_commit: Optional commit to diff from. Defaults to first process commit.

    Returns:
        JSON string with the diff output or an error.
    """
    if not task_id:
        return json.dumps({"error": "Missing X-Wiggy-Task-ID header."})

    worktree = _resolve_worktree(repo, task_id)
    if not worktree:
        return json.dumps(
            {"error": f"No worktree found for task '{task_id}'."}
        )

    since = _resolve_since_commit(repo, process_id, since_commit)
    if not since:
        return json.dumps(
            {"error": "No commit reference found. Provide since_commit or ensure "
             "the process has recorded commits."}
        )

    cmd = ["git", "diff", f"{since}..HEAD"]
    try:
        result = subprocess.run(
            cmd,
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "git diff timed out."})
    except FileNotFoundError:
        return json.dumps({"error": f"Worktree directory not found: {worktree}"})

    if result.returncode != 0:
        return json.dumps({"error": f"git diff failed: {result.stderr.strip()}"})

    diff_output = result.stdout
    truncated = False
    if len(diff_output.encode()) > _MAX_DIFF_BYTES:
        diff_output = diff_output[: _MAX_DIFF_BYTES]
        truncated = True

    response: dict[str, Any] = {
        "diff": diff_output,
        "since_commit": since,
        "truncated": truncated,
    }
    if truncated:
        response["note"] = (
            f"Output truncated to {_MAX_DIFF_BYTES // 1024}KB. "
            "Use since_commit to narrow the range."
        )
    return json.dumps(response)


def handle_get_commit_log(
    repo: TaskHistoryRepository,
    task_id: str | None,
    process_id: str,
    since_commit: str | None = None,
) -> str:
    """Handle the get_commit_log MCP tool call.

    Returns commit messages since the process started.

    Args:
        repo: The task history repository.
        task_id: The task ID from X-Wiggy-Task-ID header (for worktree lookup).
        process_id: The current process ID (for earliest commit lookup).
        since_commit: Optional commit to log from. Defaults to first process commit.

    Returns:
        JSON string with list of {hash, message} objects or an error.
    """
    if not task_id:
        return json.dumps({"error": "Missing X-Wiggy-Task-ID header."})

    worktree = _resolve_worktree(repo, task_id)
    if not worktree:
        return json.dumps(
            {"error": f"No worktree found for task '{task_id}'."}
        )

    since = _resolve_since_commit(repo, process_id, since_commit)
    if not since:
        return json.dumps(
            {"error": "No commit reference found. Provide since_commit or ensure "
             "the process has recorded commits."}
        )

    cmd = ["git", "log", "--oneline", f"{since}..HEAD"]
    try:
        result = subprocess.run(
            cmd,
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "git log timed out."})
    except FileNotFoundError:
        return json.dumps({"error": f"Worktree directory not found: {worktree}"})

    if result.returncode != 0:
        return json.dumps({"error": f"git log failed: {result.stderr.strip()}"})

    commits: list[dict[str, str]] = []
    for line in result.stdout.strip().splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            commits.append({"hash": parts[0], "message": parts[1]})
        elif parts[0]:
            commits.append({"hash": parts[0], "message": ""})

    return json.dumps({"since_commit": since, "commits": commits})
