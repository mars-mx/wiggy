"""Process orchestrator — sequential step execution engine."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from wiggy.config.schema import (
    OrchestratorConfig,
    WiggyConfig,
    resolve_orchestrator_config,
)
from wiggy.console import console
from wiggy.executors import get_executor
from wiggy.git.worktree import WorktreeInfo
from wiggy.history import TaskHistoryRepository
from wiggy.history.models import TaskLog
from wiggy.mcp import MCP_TOOL_NAMES, WiggyMCPServer, resolve_mcp_bind_host
from wiggy.processes.base import (
    OrchestratorDecision,
    ProcessRun,
    ProcessSpec,
    StepResult,
)
from wiggy.runner import resolve_engine
from wiggy.tasks import get_task_by_name

if TYPE_CHECKING:
    from wiggy.monitor import Monitor

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


def build_orchestrator_context_prompt(
    process_run: ProcessRun,
    phase: str,
    step_index: int,
) -> str:
    """Build a concise orientation block for an orchestrator invocation.

    Args:
        process_run: The live process run state.
        phase: The orchestrator phase (pre_step, post_step, finalize).
        step_index: The current step index.
    """
    total = len(process_run.steps)
    completed_count = len([r for r in process_run.results if r.success])

    lines = [
        f"Process: {process_run.spec.name} ({process_run.process_id})",
        f"Phase: {phase} for step {step_index + 1} of {total}",
    ]

    if step_index < total:
        step = process_run.steps[step_index]
        step_desc = step.task
        if step.prompt:
            step_desc += f" — {step.prompt}"
        lines.append(f"Step: {step_desc}")

    lines.append(f"Completed steps: {completed_count}/{total}")

    return "\n".join(lines)


def _run_orchestrator_phase(
    phase: str,
    step_index: int,
    process_run: ProcessRun,
    orchestrator_config: OrchestratorConfig,
    repo: TaskHistoryRepository,
    mcp_port: int | None,
    worktree_info: WorktreeInfo | None,
    engine_name: str | None,
    git_author_name: str | None,
    git_author_email: str | None,
    monitor: Monitor | None = None,
) -> OrchestratorDecision | None:
    """Run a single orchestrator phase (pre_step, post_step, or finalize).

    Returns the orchestrator's decision for pre_step/finalize phases,
    or None for post_step (which is purely informational) or on failure.
    """
    # Map phase to task suffix
    suffix_map = {"pre_step": "pre", "post_step": "post", "finalize": "finalize"}
    suffix = suffix_map.get(phase)
    if suffix is None:
        logger.warning("Unknown orchestrator phase: %s", phase)
        return None

    task_name = f"orchestrator-{suffix}"

    try:
        # Load task definition
        task_spec = get_task_by_name(task_name)
        if task_spec is None:
            logger.warning("Orchestrator task not found: %s", task_name)
            return None

        # Resolve engine: orchestrator config > process engine > auto-detect
        orch_engine_name = orchestrator_config.engine or engine_name
        resolved_engine = resolve_engine(orch_engine_name)
        if resolved_engine is None:
            logger.warning("Could not resolve engine for orchestrator")
            return None

        # Resolve model
        effective_model = orchestrator_config.model

        # Build context prompt
        context_prompt = build_orchestrator_context_prompt(
            process_run, phase, step_index
        )

        # Build extra_args with task prompt
        extra_args: tuple[str, ...] = ()
        if task_spec.source:
            prompt_path = task_spec.source / "prompt.md"
            if prompt_path.exists():
                task_prompt_content = prompt_path.read_text(encoding="utf-8").strip()
                if task_prompt_content:
                    extra_args = ("--append-system-prompt", task_prompt_content)

        # Add context prompt as system prompt
        extra_args = (*extra_args, "--append-system-prompt", context_prompt)

        # Resolve tools from task spec
        tools = task_spec.tools
        allowed_tools: list[str] | None = None
        if tools and tools != ("*",):
            allowed_tools = list(tools)

        # When MCP is enabled and tools are restricted, add MCP tool names
        if mcp_port is not None and allowed_tools is not None:
            allowed_tools = allowed_tools + list(MCP_TOOL_NAMES)

        # Create TaskLog
        task_id = secrets.token_hex(4)
        parent_id = process_run.results[-1].task_id if process_run.results else None
        start_time = datetime.now(UTC)

        task_log = TaskLog(
            task_id=task_id,
            process_id=process_run.process_id,
            executor_id=1,
            created_at=start_time.isoformat(),
            branch=worktree_info.branch if worktree_info else "main",
            worktree=str(worktree_info.path) if worktree_info else str(Path.cwd()),
            main_repo=(
                str(worktree_info.main_repo) if worktree_info else str(Path.cwd())
            ),
            engine=resolved_engine.name,
            model=effective_model,
            task_name=task_name,
            prompt=context_prompt,
            prompt_hash=_hash_prompt(context_prompt),
            parent_id=parent_id,
            is_orchestrator=True,
        )
        repo.create(task_log)

        # Create executor and run
        orch_label = f"orchestrator-{suffix}"
        step_label = f"Step {step_index + 1}/{len(process_run.steps)}"
        if monitor:
            monitor.set_step(
                1, task_name=orch_label, step_label=step_label
            )
        else:
            console.print(
                f"[dim]Orchestrator ({suffix}) for step "
                f"{step_index + 1}/{len(process_run.steps)}...[/dim]"
            )

        executor = get_executor(
            name="docker",
            image=orchestrator_config.image,
            model=effective_model,
            quiet=True,
            extra_args=extra_args,
            allowed_tools=allowed_tools,
            worktree_info=worktree_info,
            mount_cwd=worktree_info is None,
            mcp_port=mcp_port,
            git_author_name=git_author_name,
            git_author_email=git_author_email,
        )
        executor.set_task_id(task_id)
        executor.setup(resolved_engine, context_prompt)

        try:
            for msg in executor.run():
                if monitor:
                    monitor.update(1, msg)
                elif msg.content:
                    console.print(msg.content)
        finally:
            executor.teardown()

        # Record completion
        end_time = datetime.now(UTC)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)
        exit_code = executor.exit_code or 0
        success = exit_code == 0
        summary = executor.summary

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

        # Post-step phase is purely informational — no decision expected
        if phase == "post_step":
            return None

        # Read decisions from DB and return the latest one matching this task_id
        decisions = repo.get_orchestrator_decisions(process_run.process_id)
        for decision in reversed(decisions):
            if decision.task_id == task_id:
                return decision

        # Default to "proceed" if no decision was recorded
        return OrchestratorDecision(
            phase=phase,
            step_index=step_index,
            decision="proceed",
            reasoning="No explicit decision recorded, defaulting to proceed.",
            task_id=task_id,
            created_at=datetime.now(UTC).isoformat(),
        )

    except Exception:
        logger.warning(
            "Orchestrator phase '%s' failed, continuing process", phase, exc_info=True
        )
        console.print(
            f"[dim yellow]Orchestrator ({suffix}) failed, "
            f"continuing without orchestration[/dim yellow]"
        )
        return None


def run_process(
    process_spec: ProcessSpec,
    engine_name: str | None = None,
    model_override: str | None = None,
    prompt: str | None = None,
    worktree_info: WorktreeInfo | None = None,
    git_author_name: str | None = None,
    git_author_email: str | None = None,
    config: WiggyConfig | None = None,
    monitor: Monitor | None = None,
) -> ProcessRun:
    """Execute a process sequentially, running each step via Docker.

    Args:
        process_spec: The process specification to execute.
        engine_name: Engine override (applied to all steps unless step overrides).
        model_override: Model override (applied to all steps unless step overrides).
        prompt: Additional user prompt appended to each step's prompt.
        worktree_info: WorktreeInfo for git worktree to mount.
        git_author_name: Git author name for commits inside the container.
        git_author_email: Git author email for commits inside the container.
        config: WiggyConfig for orchestrator settings and other global config.

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
        if monitor:
            monitor.update_mcp(host=mcp_bind_host, port=mcp_port)
        else:
            console.print(
                f"[dim]MCP server started on {mcp_bind_host}:{mcp_port}[/dim]"
            )
    except Exception:
        logger.warning(
            "MCP server failed to start, continuing without MCP", exc_info=True
        )
        if not monitor:
            console.print(
                "[dim yellow]MCP server failed to start, "
                "continuing without MCP[/dim yellow]"
            )

    # Resolve orchestrator configuration
    orchestrator_config = resolve_orchestrator_config(
        config or WiggyConfig(), process_spec.orchestrator
    )

    # Track injection counts per origin step index to guard against loops
    injection_counts: dict[int, int] = {}

    try:
        while process_run.current_index < len(process_run.steps):
            step = process_run.steps[process_run.current_index]
            step_num = process_run.current_index + 1
            total = len(process_run.steps)

            if monitor:
                monitor.set_step(
                    1,
                    task_name=step.task,
                    step_label=f"Step {step_num}/{total}",
                )
            else:
                console.print(
                    f"\n[bold]Step {step_num}/{total}: {step.task}[/bold]"
                )

            # Orchestrator pre-step
            if orchestrator_config.enabled and not step.skip_orchestrator:
                decision = _run_orchestrator_phase(
                    "pre_step",
                    process_run.current_index,
                    process_run,
                    orchestrator_config,
                    repo,
                    mcp_port,
                    worktree_info,
                    engine_name,
                    git_author_name,
                    git_author_email,
                    monitor=monitor,
                )
                if decision:
                    process_run.orchestrator_decisions.append(decision)
                    if decision.decision == "abort":
                        if not monitor:
                            console.print(
                                f"[yellow]Orchestrator aborted: "
                                f"{decision.reasoning}[/yellow]"
                            )
                        break
                    if decision.decision == "inject":
                        current_idx = process_run.current_index
                        if (
                            injection_counts.get(current_idx, 0)
                            >= orchestrator_config.max_injections
                        ):
                            logger.warning(
                                "Injection limit (%d) reached for step %d, "
                                "overriding to 'proceed'",
                                orchestrator_config.max_injections,
                                current_idx,
                            )
                            if not monitor:
                                console.print(
                                    f"[yellow]Injection limit reached for step "
                                    f"{current_idx + 1}, proceeding[/yellow]"
                                )
                        else:
                            injection_counts[current_idx] = (
                                injection_counts.get(current_idx, 0) + 1
                            )
                            from wiggy.processes.base import ProcessStep

                            new_steps = [
                                ProcessStep(
                                    task=s.task,
                                    engine=s.engine,
                                    model=s.model,
                                    tools=s.tools,
                                    prompt=s.prompt,
                                    origin_step_index=current_idx,
                                )
                                for s in decision.injected_steps
                            ]
                            process_run.steps[
                                current_idx:current_idx
                            ] = new_steps
                            total = len(process_run.steps)
                            if monitor:
                                monitor.update_steps(
                                    [s.task for s in process_run.steps]
                                )
                            else:
                                console.print(
                                    f"[dim]Injected {len(new_steps)} step(s) "
                                    f"before step {current_idx + 1} "
                                    f"(total now {total})[/dim]"
                                )
                            continue

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
            # --append-system-prompt takes a string, not a file path,
            # so we read the file contents on the host and pass them directly.
            if task_spec.source:
                prompt_path = task_spec.source / "prompt.md"
                if prompt_path.exists():
                    task_prompt_content = prompt_path.read_text(
                        encoding="utf-8"
                    ).strip()
                    if task_prompt_content:
                        extra_args = (
                            "--append-system-prompt",
                            task_prompt_content,
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
                git_author_name=git_author_name,
                git_author_email=git_author_email,
            )
            executor.set_task_id(task_id)
            executor.setup(resolved_engine, combined_prompt)

            try:
                for msg in executor.run():
                    if monitor:
                        monitor.update(1, msg)
                    elif msg.content:
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

            # Orchestrator post-step
            if orchestrator_config.enabled and not step.skip_orchestrator:
                _run_orchestrator_phase(
                    "post_step",
                    process_run.current_index,
                    process_run,
                    orchestrator_config,
                    repo,
                    mcp_port,
                    worktree_info,
                    engine_name,
                    git_author_name,
                    git_author_email,
                    monitor=monitor,
                )

            if success:
                if monitor:
                    monitor.set_worker_done(1, success=True)
                else:
                    console.print(
                        f"[green]Step {step_num}/{total} completed: "
                        f"{step.task}[/green]"
                    )
            else:
                if monitor:
                    monitor.set_worker_done(1, success=False)
                else:
                    console.print(
                        f"[red]Step {step_num}/{total} failed: {step.task} "
                        f"(exit code {exit_code})[/red]"
                    )
                break  # l. Fail-fast

            process_run.current_index += 1

        # Orchestrator finalize after all steps complete
        if orchestrator_config.enabled:
            _run_orchestrator_phase(
                "finalize",
                len(process_run.steps),
                process_run,
                orchestrator_config,
                repo,
                mcp_port,
                worktree_info,
                engine_name,
                git_author_name,
                git_author_email,
                monitor=monitor,
            )

        # Query for pr_description artifact to populate pr_body
        artifacts = repo.get_artifacts_by_process_id(process_id)
        for artifact in reversed(artifacts):
            if artifact.template_name == "pr_description":
                process_run.pr_body = artifact.content
                break

    finally:
        try:
            mcp_server.stop()
        except Exception:
            logger.warning("MCP server failed to stop cleanly", exc_info=True)

    return process_run
