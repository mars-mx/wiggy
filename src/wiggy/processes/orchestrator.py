"""Process orchestrator — sequential step execution engine."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path

from wiggy.console import console
from wiggy.executors import get_executor
from wiggy.git.worktree import WorktreeInfo
from wiggy.history import TaskHistoryRepository
from wiggy.history.models import TaskLog
from wiggy.mcp import MCP_TOOL_NAMES, WiggyMCPServer, resolve_mcp_bind_host
from wiggy.processes.base import ProcessRun, ProcessSpec, StepResult
from wiggy.runner import resolve_engine
from wiggy.tasks import get_task_by_name

logger = logging.getLogger(__name__)


def _hash_prompt(prompt: str | None) -> str | None:
    """Generate SHA256[:16] hash of prompt for deduplication."""
    if prompt is None:
        return None
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def build_process_status_prompt(
    process_run: ProcessRun,
    repo: TaskHistoryRepository | None = None,
) -> str:
    """Build a status prompt describing the process state for injection.

    This string is passed via --append-system-prompt so the AI engine
    understands its position within the multi-step process.

    Args:
        process_run: The live process run state.
        repo: Optional history repository for fetching completed step summaries.
    """
    lines: list[str] = [
        "You are running as part of a multi-step process.",
        "You have access to wiggy MCP tools:",
        "- Use `read_result_summary` to load context from previous steps",
        "- Use `write_result` before finishing to pass your findings to the next step",
        "",
        f"## Process: {process_run.spec.name}",
        process_run.spec.description,
        "",
        "## Steps:",
    ]

    for i, step in enumerate(process_run.steps):
        if i < process_run.current_index:
            status = "[COMPLETED]"
        elif i == process_run.current_index:
            status = "[CURRENT (you are here)]"
        else:
            status = "[PENDING]"
        lines.append(f"  {i + 1}. {step.task} {status}")

    # Completed step summaries
    completed_results = [
        r for r in process_run.results if r.step_index < process_run.current_index
    ]

    if completed_results and repo is not None:
        lines.append("")
        lines.append("## Completed Step Summaries:")

        for result in completed_results:
            task_result = repo.get_result_by_task_id(result.task_id)
            if task_result and task_result.summary_text:
                summary = task_result.summary_text[:500]
                lines.append("")
                lines.append(f"### {result.task_name} (step {result.step_index + 1}):")
                lines.append(summary)

    current_step = process_run.steps[process_run.current_index]
    lines.append("")
    lines.append(f"Current step: {current_step.task}")

    return "\n".join(lines)


def run_process(
    process_spec: ProcessSpec,
    engine_name: str | None = None,
    model_override: str | None = None,
    prompt: str | None = None,
    worktree_info: WorktreeInfo | None = None,
) -> ProcessRun:
    """Execute a process sequentially, running each step via Docker.

    Args:
        process_spec: The process specification to execute.
        engine_name: Engine override (applied to all steps unless step overrides).
        model_override: Model override (applied to all steps unless step overrides).
        prompt: Additional user prompt appended to each step's prompt.

    Returns:
        ProcessRun with results for each completed step.
    """
    process_id = secrets.token_hex(4)
    process_run = ProcessRun(
        process_id=process_id, spec=process_spec, worktree_info=worktree_info
    )

    repo = TaskHistoryRepository()

    # Start shared MCP server for all steps
    mcp_bind_host = resolve_mcp_bind_host()
    mcp_server = WiggyMCPServer(repo=repo, process_id=process_id, host=mcp_bind_host)
    mcp_port: int | None = None
    try:
        mcp_port = mcp_server.start()
        console.print(f"[dim]MCP server started on {mcp_bind_host}:{mcp_port}[/dim]")
    except Exception:
        logger.warning(
            "MCP server failed to start, continuing without MCP", exc_info=True
        )
        console.print(
            "[dim yellow]MCP server failed to start, "
            "continuing without MCP[/dim yellow]"
        )

    try:
        while process_run.current_index < len(process_run.steps):
            step = process_run.steps[process_run.current_index]
            step_num = process_run.current_index + 1
            total = len(process_run.steps)

            console.print(f"\n[bold]Step {step_num}/{total}: {step.task}[/bold]")

            # a. Load referenced TaskSpec
            task_spec = get_task_by_name(step.task)
            if task_spec is None:
                console.print(f"[red]Unknown task: {step.task}[/red]")
                console.print(
                    "[dim]Run 'wiggy task list' to see available tasks.[/dim]"
                )
                break

            # b. Resolve engine: step > cli arg > auto-detect
            step_engine_name = step.engine or engine_name
            resolved_engine = resolve_engine(step_engine_name)
            if resolved_engine is None:
                break

            # c. Resolve model: step > cli arg > task spec
            effective_model = step.model or model_override or task_spec.model

            # d. Resolve tools: step > task spec
            tools = step.tools if step.tools is not None else task_spec.tools
            allowed_tools: list[str] | None = None
            if tools and tools != ("*",):
                allowed_tools = list(tools)

            # e. Build status prompt
            status_prompt = build_process_status_prompt(process_run, repo=repo)

            # f. Build extra_args with --append-system-prompt for task prompt
            extra_args: tuple[str, ...] = ()

            # Include task prompt.md if available
            if task_spec.source:
                prompt_path = task_spec.source / "prompt.md"
                if prompt_path.exists():
                    container_prompt_path = (
                        f"/home/wiggy/.wiggy/tasks/{step.task}/prompt.md"
                    )
                    extra_args = (
                        "--append-system-prompt",
                        container_prompt_path,
                        *extra_args,
                    )

            # When MCP is enabled and tools are restricted, add MCP tool names
            if mcp_port is not None and allowed_tools is not None:
                allowed_tools = allowed_tools + list(MCP_TOOL_NAMES)

            # g. Combine prompts: status prompt + step.prompt + user prompt
            prompt_parts: list[str] = [status_prompt]
            if step.prompt:
                prompt_parts.append(step.prompt)
            if prompt:
                prompt_parts.append(prompt)
            combined_prompt = "\n\n".join(prompt_parts)

            # h. Create TaskLog
            task_id = secrets.token_hex(4)
            parent_id = process_run.results[-1].task_id if process_run.results else None
            start_time = datetime.now(UTC)

            task_log = TaskLog(
                task_id=task_id,
                process_id=process_id,
                executor_id=1,
                created_at=start_time.isoformat(),
                branch=worktree_info.branch if worktree_info else "main",
                worktree=str(worktree_info.path) if worktree_info else str(Path.cwd()),
                main_repo=(
                    str(worktree_info.main_repo)
                    if worktree_info
                    else str(Path.cwd())
                ),
                engine=resolved_engine.name,
                model=effective_model,
                task_name=step.task,
                prompt=combined_prompt,
                prompt_hash=_hash_prompt(combined_prompt),
                parent_id=parent_id,
            )
            repo.create(task_log)

            # i. Create Docker executor, run, collect output
            executor = get_executor(
                name="docker",
                model=effective_model,
                quiet=True,
                extra_args=extra_args,
                allowed_tools=allowed_tools,
                worktree_info=worktree_info,
                mount_cwd=worktree_info is None,
                mcp_port=mcp_port,
            )
            executor.set_task_id(task_id)
            executor.setup(resolved_engine, combined_prompt)

            try:
                for msg in executor.run():
                    if msg.content:
                        console.print(msg.content)
            finally:
                executor.teardown()

            # Collect results
            end_time = datetime.now(UTC)
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
            exit_code = executor.exit_code or 0
            success = exit_code == 0
            summary = executor.summary

            # k. Record completion in history DB
            repo.complete(
                task_id,
                success=success,
                exit_code=exit_code,
                finished_at=end_time.isoformat(),
                duration_ms=duration_ms,
                error_message=None if success else f"Exit code: {exit_code}",
                total_cost=summary.total_cost if summary else None,
                input_tokens=summary.input_tokens if summary else None,
                output_tokens=summary.output_tokens if summary else None,
            )

            # j. Create StepResult and append
            step_result = StepResult(
                step_index=process_run.current_index,
                task_name=step.task,
                task_id=task_id,
                success=success,
                exit_code=exit_code,
                duration_ms=duration_ms,
            )
            process_run.results.append(step_result)

            if success:
                console.print(
                    f"[green]Step {step_num}/{total} completed: {step.task}[/green]"
                )
            else:
                console.print(
                    f"[red]Step {step_num}/{total} failed: {step.task} "
                    f"(exit code {exit_code})[/red]"
                )
                break  # l. Fail-fast

            process_run.current_index += 1

    finally:
        try:
            mcp_server.stop()
        except Exception:
            logger.warning("MCP server failed to stop cleanly", exc_info=True)

    return process_run
