"""Command-line interface for wiggy."""

import hashlib
import logging
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from queue import Queue

import click

from wiggy import __version__
from wiggy.config.init import (
    copy_default_processes,
    copy_default_tasks,
    copy_default_templates,
    ensure_wiggy_dir,
)
from wiggy.config.loader import (
    get_home_config_path,
    home_config_exists,
    load_config,
    local_config_exists,
    resolve_git_author,
)
from wiggy.config.preflight import run_all_checks
from wiggy.config.wizard import run_home_wizard, run_local_wizard, show_current_config
from wiggy.console import console
from wiggy.executors import DEFAULT_EXECUTOR, EXECUTORS, get_executors
from wiggy.executors.base import Executor
from wiggy.git import (
    GitOperations,
    NotAGitRepoError,
    WorktreeError,
    WorktreeInfo,
    WorktreeManager,
)
from wiggy.history import (
    TaskHistoryRepository,
    TaskLog,
    TaskNotFoundError,
    cleanup_old_tasks,
)
from wiggy.mcp import MCP_TOOL_NAMES, WiggyMCPServer, resolve_mcp_bind_host
from wiggy.monitor import Monitor
from wiggy.parsers.messages import MessageType, ParsedMessage
from wiggy.processes import (
    ProcessSpec,
    get_all_processes,
    get_process_by_name,
    run_process,
)
from wiggy.processes.loader import get_global_processes_path, get_local_processes_path
from wiggy.runner import resolve_engine
from wiggy.tasks import (
    TaskSpec,
    get_all_tasks,
    get_global_tasks_path,
    get_local_tasks_path,
    get_task_by_name,
)

logger = logging.getLogger(__name__)


def _hash_prompt(prompt: str | None) -> str | None:
    """Generate SHA256[:16] hash of prompt for deduplication."""
    if prompt is None:
        return None
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def _check_task_result(
    repo: TaskHistoryRepository, task_id: str, task_name: str | None
) -> None:
    """Check if the task wrote a result and log a warning if not."""
    result = repo.get_result_by_task_id(task_id)
    if result is None:
        display_name = task_name or task_id
        logger.warning("Task '%s' did not call write_result", display_name)
        console.print(
            f"[dim yellow]Warning: Task '{display_name}' did not write a result"
            "[/dim yellow]"
        )


def build_mcp_system_prompt(
    process_id: str,
    current_task_name: str,
    completed_steps: list[str],
    repo: TaskHistoryRepository,
) -> str:
    """Build a system prompt hint for MCP-aware tasks.

    Returns a prompt fragment describing available MCP tools and prior step
    context for multi-step processes.
    """
    lines = [
        "You are running as part of a multi-step process. "
        "You have access to wiggy MCP tools:",
        "",
        "Results:",
        "- Use `read_result_summary` to load context from previous steps",
        "- Use `write_result` before finishing to pass your findings to the next step",
        "",
        "Knowledge base:",
        "- Use `write_knowledge` to persist decisions or learnings across tasks",
        "- Use `get_knowledge` to retrieve a knowledge entry by key",
        "- Use `search_knowledge` to find relevant knowledge, results, and artifacts",
        "- Use `view_knowledge_history` to see all versions of a knowledge entry",
        "",
        "Artifacts:",
        "- Use `write_artifact` to store structured documents (PRDs, docs, ADRs)",
        "- Use `load_artifact` to retrieve an artifact by ID",
        "- Use `list_artifacts` to browse artifacts for the current process",
        "- Use `list_artifact_templates` and `load_artifact_template` to use templates",
    ]

    if completed_steps:
        steps_str = ", ".join(f"{s} (completed)" for s in completed_steps)
        lines.append(f"\nPrevious steps in this process: {steps_str}")

    lines.append(f"Current step: {current_task_name}")

    return "\n".join(lines)


def _build_single_task_mcp_prompt() -> str:
    """Build a simpler MCP system prompt for single task execution."""
    return (
        "You have access to wiggy MCP tools:\n"
        "\n"
        "Results:\n"
        "- Use `write_result` before finishing to save your findings\n"
        "- Use `read_result_summary` to load context from previous "
        "task executions\n"
        "\n"
        "Knowledge base:\n"
        "- Use `write_knowledge` to persist decisions or learnings across tasks\n"
        "- Use `get_knowledge` to retrieve a knowledge entry by key\n"
        "- Use `search_knowledge` to find relevant knowledge, results, and artifacts\n"
        "- Use `view_knowledge_history` to see all versions of a knowledge entry\n"
        "\n"
        "Artifacts:\n"
        "- Use `write_artifact` to store structured documents (PRDs, docs, ADRs)\n"
        "- Use `load_artifact` to retrieve an artifact by ID\n"
        "- Use `list_artifacts` to browse artifacts for the current task\n"
        "- Use `list_artifact_templates` and `load_artifact_template` to use templates"
    )


def _resolve_resume_target(
    repo: TaskHistoryRepository,
    resume_task: str | None,
    resume_branch: str | None,
    resume_session: str | None,
) -> TaskLog:
    """Resolve exactly one resume option to a TaskLog."""
    if resume_task:
        task = repo.get_by_task_id(resume_task)
        if not task:
            raise TaskNotFoundError("task_id", resume_task)
        return task

    if resume_branch:
        task = repo.get_by_branch(resume_branch)
        if not task:
            raise TaskNotFoundError("branch", resume_branch)
        return task

    if resume_session:
        task = repo.get_by_session_id(resume_session)
        if not task:
            raise TaskNotFoundError("session_id", resume_session)
        return task

    raise ValueError("No resume option provided")


def version_callback(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    """Print version and exit."""
    if not value or ctx.resilient_parsing:
        return
    console.print(f"wiggy [bold cyan]{__version__}[/bold cyan]")
    ctx.exit()


@click.group(invoke_without_command=True)
@click.option(
    "--version",
    is_flag=True,
    callback=version_callback,
    expose_value=False,
    is_eager=True,
    help="Show version and exit.",
)
@click.pass_context
def main(ctx: click.Context) -> None:
    """Wiggy - Ralph Wiggum loop AI software development CLI."""
    ensure_wiggy_dir()

    if ctx.invoked_subcommand is None:
        console.print("[bold]wiggy[/bold] - persistent iteration for AI development")
        console.print("\nRun [cyan]wiggy --help[/cyan] for available commands.")


@main.command()
@click.argument("prompt", required=False)
@click.option(
    "--engine",
    "-e",
    help="AI engine to use (e.g., claude, opencode, codex).",
)
@click.option(
    "--executor",
    "-x",
    type=click.Choice(list(EXECUTORS.keys())),
    default=DEFAULT_EXECUTOR,
    help="Executor to use.",
)
@click.option(
    "--image",
    "-i",
    help="Docker image to use (overrides engine default). Only for docker executor.",
)
@click.option(
    "--parallel",
    "-p",
    type=int,
    default=1,
    help="Number of executor instances to spawn in parallel.",
)
@click.option(
    "--model",
    "-m",
    help="Model to use (overrides engine default). Passed to engine CLI.",
)
@click.option(
    "--worktree",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Path to existing git worktree to use.",
)
@click.option(
    "--worktree-root",
    type=click.Path(file_okay=False, path_type=Path),
    envvar="WIGGY_WORKTREE_ROOT",
    help="Root directory for auto-created worktrees.",
)
@click.option(
    "--push/--no-push",
    default=True,
    help="Push to remote after execution (default: push).",
)
@click.option(
    "--pr/--no-pr",
    default=True,
    help="Create PR after execution (default: create PR).",
)
@click.option(
    "--remote",
    default="origin",
    envvar="WIGGY_REMOTE",
    help="Git remote to push to (default: origin).",
)
@click.option(
    "--keep-worktree",
    is_flag=True,
    default=False,
    help="Keep worktree after execution (default: delete).",
)
@click.option(
    "--resume-task",
    "resume_task",
    help="Resume by task_id (8 hex chars).",
)
@click.option(
    "--resume-branch",
    "resume_branch",
    help="Resume by branch name.",
)
@click.option(
    "--resume-session",
    "resume_session",
    help="Resume by engine session_id.",
)
@click.option(
    "--continue-from",
    "continue_from",
    help="Create child task linked to parent task_id.",
)
@click.pass_context
def run(
    ctx: click.Context,
    prompt: str | None,
    engine: str | None,
    executor: str,
    image: str | None,
    parallel: int,
    model: str | None,
    worktree: Path | None,
    worktree_root: Path | None,
    push: bool,
    pr: bool,
    remote: str,
    keep_worktree: bool,
    resume_task: str | None,
    resume_branch: str | None,
    resume_session: str | None,
    continue_from: str | None,
) -> None:
    """Run the wiggy loop."""
    # Load config and apply values for options not explicitly set on CLI
    config = load_config()

    def _from_cli(param_name: str) -> bool:
        """Check if a parameter was explicitly set on the command line."""
        source = ctx.get_parameter_source(param_name)
        return source == click.core.ParameterSource.COMMANDLINE

    # Override with config values if not explicitly set on CLI
    if not _from_cli("engine") and config.engine:
        engine = config.engine
    if not _from_cli("executor") and config.executor:
        executor = config.executor
    if not _from_cli("image") and config.image:
        image = config.image
    if not _from_cli("parallel") and config.parallel is not None:
        parallel = config.parallel
    if not _from_cli("model") and config.model:
        model = config.model
    if not _from_cli("worktree_root") and config.worktree_root:
        worktree_root = Path(config.worktree_root)
    if not _from_cli("push") and config.push is not None:
        push = config.push
    if not _from_cli("pr") and config.pr is not None:
        pr = config.pr
    if not _from_cli("remote") and config.remote:
        remote = config.remote
    if not _from_cli("keep_worktree") and config.keep_worktree is not None:
        keep_worktree = config.keep_worktree

    # Validate mutually exclusive resume options
    resume_opts = [resume_task, resume_branch, resume_session]
    if sum(1 for opt in resume_opts if opt) > 1:
        console.print(
            "[red]Only one of --resume-task, --resume-branch, "
            "--resume-session allowed[/red]"
        )
        raise SystemExit(1)

    # Initialize task history repository
    repo = TaskHistoryRepository()

    # Handle resume if specified
    parent_task: TaskLog | None = None
    if any(resume_opts):
        try:
            parent_task = _resolve_resume_target(
                repo, resume_task, resume_branch, resume_session
            )
            console.print(f"[dim]Resuming from task: {parent_task.task_id}[/dim]")
            console.print(f"[dim]Branch: {parent_task.branch}[/dim]")
            # Use parent's branch worktree for resume
            worktree = Path(parent_task.worktree)
        except TaskNotFoundError as e:
            console.print(f"[red]Task not found: {e}[/red]")
            raise SystemExit(1) from None

    # Handle continue-from (parent linking)
    if continue_from:
        parent = repo.get_by_task_id(continue_from)
        if not parent:
            console.print(f"[red]Parent task not found: {continue_from}[/red]")
            raise SystemExit(1)
        parent_task = parent

    resolved_engine = resolve_engine(engine)
    if resolved_engine is None:
        raise SystemExit(1)

    # Validate --image is only used with docker executor
    if image and executor != "docker":
        console.print("[red]--image can only be used with docker executor[/red]")
        raise SystemExit(1)

    # Git worktree setup (only for docker executor)
    worktree_infos: list[WorktreeInfo] = []
    wt_manager: WorktreeManager | None = None

    if executor == "docker":
        try:
            wt_manager = WorktreeManager()

            if worktree:
                # Use existing worktree (only one, shared by all parallel executors)
                info = wt_manager.use_existing_worktree(worktree)
                worktree_infos = [info] * parallel
                console.print(f"[dim]Using existing worktree: {info.path}[/dim]")
                console.print(f"[dim]Branch: {info.branch}[/dim]")
            else:
                # Create new worktree(s)
                for i in range(1, parallel + 1):
                    suffix = f"exec{i}" if parallel > 1 else ""
                    info = wt_manager.create_worktree(
                        worktree_root=worktree_root,
                        suffix=suffix,
                    )
                    worktree_infos.append(info)
                    console.print(f"[dim]Created worktree: {info.path}[/dim]")
                    console.print(f"[dim]Branch: {info.branch}[/dim]")

        except NotAGitRepoError as e:
            console.print(f"[red]Error: {e}[/red]")
            console.print("[red]wiggy requires a git repository to run.[/red]")
            raise SystemExit(1) from None
        except WorktreeError as e:
            console.print(f"[red]Worktree error: {e}[/red]")
            raise SystemExit(1) from None

    # Resolve git author identity for Docker containers
    git_author_name: str | None = None
    git_author_email: str | None = None
    if executor == "docker":
        git_author_name, git_author_email = resolve_git_author(config)

    console.print(
        f"[bold green]Starting wiggy loop with {resolved_engine.name}...[/bold green]"
    )
    console.print(f"[dim]Executor: {executor}, Parallel: {parallel}[/dim]")
    if image:
        console.print(f"[dim]Image override: {image}[/dim]")
    if model:
        console.print(f"[dim]Model override: {model}[/dim]")
    if prompt:
        console.print(f"[dim]Prompt: {prompt}[/dim]")

    # Generate process_id for this run
    process_id = secrets.token_hex(4)

    # Start MCP server for task result storage
    mcp_bind_host = resolve_mcp_bind_host()
    mcp_server = WiggyMCPServer(repo=repo, process_id=process_id, host=mcp_bind_host)
    mcp_port: int | None = None
    try:
        mcp_port = mcp_server.start()
        console.print(f"[dim]MCP server started on {mcp_bind_host}:{mcp_port}[/dim]")
    except Exception:
        logger.warning(
            "MCP server failed to start, continuing without MCP",
            exc_info=True,
        )
        console.print(
            "[dim yellow]MCP server failed to start, "
            "continuing without MCP[/dim yellow]"
        )

    try:
        # Create executor instances with worktree info
        executors = get_executors(
            name=executor,
            count=parallel,
            image=image,
            model=model,
            quiet=True,
            worktree_infos=worktree_infos if worktree_infos else None,
            mcp_port=mcp_port,
            git_author_name=git_author_name,
            git_author_email=git_author_email,
        )

        # Generate task_ids, create task log records
        task_logs: list[TaskLog] = []
        start_time = datetime.now(UTC)

        for i, ex in enumerate(executors, 1):
            task_id = secrets.token_hex(4)
            ex.set_task_id(task_id)

            # Get worktree info for this executor
            wt_info = worktree_infos[i - 1] if worktree_infos else None

            task_log = TaskLog(
                task_id=task_id,
                process_id=process_id,
                executor_id=i,
                created_at=start_time.isoformat(),
                branch=wt_info.branch if wt_info else "main",
                worktree=str(wt_info.path) if wt_info else str(Path.cwd()),
                main_repo=str(wt_info.main_repo) if wt_info else str(Path.cwd()),
                engine=resolved_engine.name,
                model=model,
                prompt=prompt,
                prompt_hash=_hash_prompt(prompt),
                parent_id=parent_task.task_id if parent_task else None,
            )
            repo.create(task_log)
            task_logs.append(task_log)
            console.print(f"[dim]Task {task_id} created for executor {i}[/dim]")

        # Create monitor for real-time status display
        monitor = Monitor(
            resolved_engine.name,
            parallel,
            model=model,
            mcp_host=mcp_bind_host if mcp_port else None,
            mcp_port=mcp_port,
        )

        # Queue for messages from executor threads: (executor_id, message or None)
        queue: Queue[tuple[int, ParsedMessage | None]] = Queue()

        # Track session_id updates per executor
        session_ids: dict[int, str | None] = {}

        def run_single(ex: Executor) -> int | None:
            """Run a single executor, pushing messages to the queue."""
            ex.setup(resolved_engine, prompt)
            try:
                for msg in ex.run():
                    queue.put((ex.executor_id, msg))
            finally:
                ex.teardown()
                queue.put((ex.executor_id, None))  # Signal completion
            return ex.exit_code

        try:
            monitor.start()

            with ThreadPoolExecutor(max_workers=parallel) as pool:
                futures = [pool.submit(run_single, ex) for ex in executors]

                # Process messages until all executors complete
                completed = 0
                while completed < parallel:
                    exec_id, msg = queue.get()
                    if msg is None:
                        completed += 1
                    else:
                        monitor.update(exec_id, msg)
                        # Capture session_id from SYSTEM_INIT messages
                        if msg.message_type == MessageType.SYSTEM_INIT:
                            engine_session_id = msg.metadata.get("session_id")
                            if engine_session_id:
                                session_ids[exec_id] = engine_session_id
                                exec_task_id = executors[exec_id - 1].task_id
                                if exec_task_id:
                                    repo.update_session_id(
                                        exec_task_id, engine_session_id
                                    )

                # Collect exit codes
                exit_codes = [f.result() for f in futures]

        finally:
            monitor.stop()

        # Complete task logs with results
        end_time = datetime.now(UTC)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        for task_log, exit_code, exec_instance in zip(
            task_logs, exit_codes, executors, strict=True
        ):
            success = exit_code == 0
            summary = exec_instance.summary
            repo.complete(
                task_log.task_id,
                success=success,
                exit_code=exit_code or 0,
                finished_at=end_time.isoformat(),
                duration_ms=duration_ms,
                error_message=None if success else f"Exit code: {exit_code}",
                total_cost=summary.total_cost if summary else None,
                input_tokens=summary.input_tokens if summary else None,
                output_tokens=summary.output_tokens if summary else None,
            )

        # Post-step validation: check if tasks wrote results
        for task_log in task_logs:
            _check_task_result(repo, task_log.task_id, task_log.task_name)

        # Check for failures
        any_failed = any(code != 0 for code in exit_codes)
    finally:
        try:
            mcp_server.stop()
        except Exception:
            logger.warning("MCP server failed to stop cleanly", exc_info=True)

    # Post-execution git operations
    if worktree_infos:
        # Use unique worktree infos for post-execution (avoid duplicates if shared)
        unique_infos = list({info.path: info for info in worktree_infos}.values())

        # Skip push/PR if any executor failed
        if any_failed:
            console.print(
                "[yellow]Executor failed - skipping push/PR, keeping worktree[/yellow]"
            )
        else:
            for info in unique_infos:
                git_ops = GitOperations(info)

                if push and git_ops.has_commits():
                    console.print(f"[dim]Pushing {info.branch} to {remote}...[/dim]")
                    if git_ops.push_to_remote(remote):
                        console.print(
                            f"[green]Pushed {info.branch} to {remote}[/green]"
                        )
                    else:
                        console.print(f"[yellow]Failed to push {info.branch}[/yellow]")

                if pr and push and git_ops.has_commits():
                    console.print(
                        f"[dim]Creating pull request for {info.branch}...[/dim]"
                    )
                    commits = git_ops.get_commit_messages()
                    body = (
                        "\n".join(f"- {msg}" for msg in commits)
                        if commits
                        else None
                    )
                    pr_url = git_ops.create_pull_request(body=body)
                    if pr_url:
                        console.print(f"[green]PR created: {pr_url}[/green]")
                    else:
                        console.print(
                            "[yellow]Failed to create PR"
                            " (is gh CLI installed?)[/yellow]"
                        )

            # Cleanup worktrees unless --keep-worktree (only on success)
            if not keep_worktree and wt_manager:
                for info in unique_infos:
                    console.print(f"[dim]Removing worktree: {info.path}[/dim]")
                    try:
                        wt_manager.remove_worktree(info, force=True)
                    except WorktreeError as e:
                        console.print(
                            f"[yellow]Failed to remove worktree: {e}[/yellow]"
                        )

    # Exit with failure code if any executor failed
    if any_failed:
        first_failure = next(code for code in exit_codes if code != 0)
        raise SystemExit(first_failure or 1)


@main.command()
def preflight() -> None:
    """Validate environment is ready (Docker, etc.)."""
    if not run_all_checks():
        raise SystemExit(1)


@main.command()
@click.option(
    "--older-than",
    default=30,
    type=int,
    help="Delete tasks older than this many days (default: 30).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be deleted without actually deleting.",
)
def cleanup(older_than: int, dry_run: bool) -> None:
    """Clean up old task history and log files.

    Deletes task records and associated log files older than the specified
    number of days. Use --dry-run to preview what would be deleted.
    """
    repo = TaskHistoryRepository()
    deleted = cleanup_old_tasks(repo, older_than_days=older_than, dry_run=dry_run)

    if dry_run:
        if deleted:
            console.print(f"[yellow]Would delete {len(deleted)} tasks:[/yellow]")
            for task_id in deleted:
                console.print(f"  - {task_id}")
        else:
            console.print("[dim]No tasks older than {older_than} days.[/dim]")
    else:
        if deleted:
            console.print(f"[green]Deleted {len(deleted)} tasks and log files.[/green]")
        else:
            console.print(
                f"[dim]No tasks older than {older_than} days to clean up.[/dim]"
            )


@main.command()
@click.option(
    "--limit",
    "-n",
    default=10,
    type=int,
    help="Number of recent tasks to show (default: 10).",
)
def history(limit: int) -> None:
    """Show recent task history.

    Displays a list of recent task executions with their status,
    branch, and other details.
    """
    repo = TaskHistoryRepository()
    tasks = repo.get_recent(limit=limit)

    if not tasks:
        console.print("[dim]No task history found.[/dim]")
        return

    console.print(f"[bold]Recent Tasks ({len(tasks)}):[/bold]\n")
    for task in tasks:
        status = (
            "[green]✓[/green]"
            if task.success
            else ("[red]✗[/red]" if task.success is False else "[yellow]?[/yellow]")
        )
        console.print(f"  {status} [cyan]{task.task_id}[/cyan] | {task.branch}")
        console.print(f"      Engine: {task.engine} | Created: {task.created_at[:19]}")
        if task.prompt:
            prompt_preview = (
                task.prompt[:50] + "..." if len(task.prompt) > 50 else task.prompt
            )
            console.print(f"      Prompt: {prompt_preview}")
        console.print()


@main.command()
@click.option(
    "--global",
    "-g",
    "global_config",
    is_flag=True,
    help="Create or update global config (~/.wiggy/config.yaml).",
)
@click.option(
    "--local",
    "-l",
    "local_config",
    is_flag=True,
    help="Create or update local config (./.wiggy/config.yaml).",
)
@click.option(
    "--show",
    is_flag=True,
    help="Show current effective configuration and exit.",
)
def init(global_config: bool, local_config: bool, show: bool) -> None:
    """Initialize wiggy configuration.

    Creates configuration files for wiggy. Without flags, runs an interactive
    wizard that checks for existing configs and guides you through setup.

    Use --global to create/update the global config (~/.wiggy/config.yaml).
    Use --local to create/update the local project config (./.wiggy/config.yaml).

    Config locations:
      - Global: ~/.wiggy/config.yaml (user defaults)
      - Local: ./.wiggy/config.yaml (project overrides)
    """
    if show:
        show_current_config()
        return

    # Explicit --global flag: create/update global config
    if global_config:
        if home_config_exists():
            home_path = get_home_config_path()
            console.print(
                f"[yellow]Global config already exists at {home_path}[/yellow]"
            )
            if click.confirm("Overwrite with new configuration?", default=False):
                run_home_wizard()
            else:
                console.print("\nNo changes made.")
        else:
            run_home_wizard()
        # Copy default tasks to global location
        copied = copy_default_tasks(local=False)
        if copied:
            console.print(
                f"[green]Copied {len(copied)} default tasks to ~/.wiggy/tasks/[/green]"
            )
        copied_procs = copy_default_processes(local=False)
        if copied_procs:
            n = len(copied_procs)
            console.print(f"[green]Copied {n} default processes[/green]")
        copied_tmpls = copy_default_templates(local=False)
        if copied_tmpls:
            n = len(copied_tmpls)
            console.print(f"[green]Copied {n} default templates[/green]")
        return

    # Explicit --local flag: create/update local config
    if local_config:
        if not home_config_exists():
            console.print(
                "[yellow]No global configuration found. "
                "Run 'wiggy init --global' first to set up defaults.[/yellow]"
            )
            return
        home_cfg = load_config()
        run_local_wizard(home_cfg)
        # Copy default tasks to local (project) location
        copied = copy_default_tasks(local=True)
        if copied:
            console.print(
                f"[green]Copied {len(copied)} default tasks to ./.wiggy/tasks/[/green]"
            )
        copied_procs = copy_default_processes(local=True)
        if copied_procs:
            n = len(copied_procs)
            console.print(f"[green]Copied {n} default processes[/green]")
        copied_tmpls = copy_default_templates(local=True)
        if copied_tmpls:
            n = len(copied_tmpls)
            console.print(f"[green]Copied {n} default templates[/green]")
        return

    # No flags: interactive flow
    if not home_config_exists():
        # First time user flow
        home_path = get_home_config_path()
        console.print(f"[yellow]No global configuration found at {home_path}[/yellow]")
        if click.confirm("Is this your first time using wiggy?", default=True):
            run_home_wizard()
            # Copy default tasks to global location
            copied = copy_default_tasks(local=False)
            if copied:
                msg = f"[green]Copied {len(copied)} tasks to ~/.wiggy/tasks/[/green]"
                console.print(msg)
            copied_procs = copy_default_processes(local=False)
            if copied_procs:
                msg = f"[green]Copied {len(copied_procs)} processes[/green]"
                console.print(msg)
            copied_tmpls = copy_default_templates(local=False)
            if copied_tmpls:
                msg = f"[green]Copied {len(copied_tmpls)} templates[/green]"
                console.print(msg)
        else:
            console.print(
                "\nTo create a global config, run [cyan]wiggy init --global[/cyan]."
            )
    else:
        # Existing user flow
        console.print(
            f"[green]Global configuration found at {get_home_config_path()}[/green]"
        )
        console.print("[dim]Use 'wiggy init --global' to update global settings.[/dim]")

        # Ensure global tasks exist
        copied = copy_default_tasks(local=False)
        if copied:
            console.print(
                f"[green]Copied {len(copied)} default tasks to ~/.wiggy/tasks/[/green]"
            )
        copied_procs = copy_default_processes(local=False)
        if copied_procs:
            n = len(copied_procs)
            console.print(f"[green]Copied {n} default processes[/green]")
        copied_tmpls = copy_default_templates(local=False)
        if copied_tmpls:
            n = len(copied_tmpls)
            console.print(f"[green]Copied {n} default templates[/green]")

        if local_config_exists():
            console.print(
                "\n[dim]Local project config already exists at .wiggy/config.yaml[/dim]"
            )
            if click.confirm("Would you like to update it?", default=False):
                home_cfg = load_config()
                run_local_wizard(home_cfg)
                # Copy any missing local tasks
                copied = copy_default_tasks(local=True)
                if copied:
                    msg = f"Copied {len(copied)} default tasks to ./.wiggy/tasks/"
                    console.print(f"[green]{msg}[/green]")
                copied_procs = copy_default_processes(local=True)
                if copied_procs:
                    msg = f"Copied {len(copied_procs)} default processes"
                    console.print(f"[green]{msg}[/green]")
                copied_tmpls = copy_default_templates(local=True)
                if copied_tmpls:
                    msg = f"Copied {len(copied_tmpls)} default templates"
                    console.print(f"[green]{msg}[/green]")
            else:
                console.print("\nNo config changes made.")
                # Still copy any missing local tasks
                copied = copy_default_tasks(local=True)
                if copied:
                    msg = f"Copied {len(copied)} default tasks to ./.wiggy/tasks/"
                    console.print(f"[green]{msg}[/green]")
                copied_procs = copy_default_processes(local=True)
                if copied_procs:
                    msg = f"Copied {len(copied_procs)} default processes"
                    console.print(f"[green]{msg}[/green]")
                copied_tmpls = copy_default_templates(local=True)
                if copied_tmpls:
                    msg = f"Copied {len(copied_tmpls)} default templates"
                    console.print(f"[green]{msg}[/green]")
        else:
            if click.confirm(
                "\nWould you like to create project-specific overrides?", default=False
            ):
                home_cfg = load_config()
                run_local_wizard(home_cfg)
                # Copy default tasks to local location
                copied = copy_default_tasks(local=True)
                if copied:
                    msg = f"Copied {len(copied)} default tasks to ./.wiggy/tasks/"
                    console.print(f"[green]{msg}[/green]")
                copied_procs = copy_default_processes(local=True)
                if copied_procs:
                    msg = f"Copied {len(copied_procs)} default processes"
                    console.print(f"[green]{msg}[/green]")
                copied_tmpls = copy_default_templates(local=True)
                if copied_tmpls:
                    msg = f"Copied {len(copied_tmpls)} default templates"
                    console.print(f"[green]{msg}[/green]")
            else:
                console.print("\nUsing global configuration.")
                # Still copy default tasks to local location
                copied = copy_default_tasks(local=True)
                if copied:
                    msg = f"Copied {len(copied)} default tasks to ./.wiggy/tasks/"
                    console.print(f"[green]{msg}[/green]")
                copied_procs = copy_default_processes(local=True)
                if copied_procs:
                    msg = f"Copied {len(copied_procs)} default processes"
                    console.print(f"[green]{msg}[/green]")
                copied_tmpls = copy_default_templates(local=True)
                if copied_tmpls:
                    msg = f"Copied {len(copied_tmpls)} default templates"
                    console.print(f"[green]{msg}[/green]")


def _get_source_label(task: TaskSpec) -> str:
    """Get a label indicating whether task is from global or local."""
    if task.source is None:
        return ""
    source_str = str(task.source)
    if ".wiggy/tasks" in source_str:
        if str(Path.cwd()) in source_str:
            return "(local)"
        return "(global)"
    return ""


def _format_tasks_context(tasks: dict[str, TaskSpec]) -> str:
    """Format tasks as context for AI prompts."""
    lines = []
    for name, spec in sorted(tasks.items()):
        tools_str = ", ".join(spec.tools) if spec.tools else "none"
        lines.append(f"### {name}")
        lines.append(spec.description.strip())
        lines.append(f"Tools: {tools_str}")
        lines.append("")
    return "\n".join(lines)


@main.group(invoke_without_command=True)
@click.pass_context
def task(ctx: click.Context) -> None:
    """Run and manage tasks.

    Use subcommands: wiggy task list, wiggy task run, wiggy task create
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@task.command("list")
@click.option("--verbose", "-v", is_flag=True, help="Show task details.")
def task_list(verbose: bool) -> None:
    """List available tasks."""
    tasks = get_all_tasks()

    if not tasks:
        console.print("[yellow]No tasks found.[/yellow]")
        console.print(
            "[dim]Run 'wiggy init' to copy default tasks to ~/.wiggy/tasks/[/dim]"
        )
        return

    console.print("[bold]Available Tasks:[/bold]\n")
    for name, spec in sorted(tasks.items()):
        source_label = _get_source_label(spec)
        console.print(f"  [cyan]{name}[/cyan] {source_label}")
        if verbose:
            console.print(f"    {spec.description.strip()}")
            tools_str = ", ".join(spec.tools) if spec.tools else "all"
            console.print(f"    [dim]Tools: {tools_str}[/dim]")
            console.print()


@task.command("run")
@click.argument("task_name")
@click.option("--engine", "-e", help="AI engine to use.")
@click.option("--model", "-m", help="Model to use (overrides task default).")
@click.option("--prompt", "-p", help="Additional prompt/instructions.")
def task_run(
    task_name: str,
    engine: str | None,
    model: str | None,
    prompt: str | None,
) -> None:
    """Run a task by name."""
    spec = get_task_by_name(task_name)
    if spec is None:
        console.print(f"[red]Unknown task: {task_name}[/red]")
        console.print("[dim]Run 'wiggy task list' to see available tasks.[/dim]")
        raise SystemExit(1)

    # Resolve engine
    resolved_engine = resolve_engine(engine)
    if resolved_engine is None:
        raise SystemExit(1)

    # Use task's model preference if not overridden
    effective_model = model or spec.model

    # Build allowed_tools from task spec
    allowed_tools: list[str] | None = None
    if spec.tools and spec.tools != ("*",):
        allowed_tools = list(spec.tools)

    # Build extra args for --append-system-prompt if task has a prompt file
    extra_args: tuple[str, ...] = ()
    if spec.source:
        prompt_path = spec.source / "prompt.md"
        if prompt_path.exists():
            # Container mount path for global tasks
            container_prompt_path = f"/home/wiggy/.wiggy/tasks/{task_name}/prompt.md"
            extra_args = ("--append-system-prompt", container_prompt_path)

    # Resolve git author identity for Docker containers
    config = load_config()
    git_author_name, git_author_email = resolve_git_author(config)

    console.print(f"[bold green]Running task: {task_name}[/bold green]")
    console.print(f"[dim]Engine: {resolved_engine.name}[/dim]")
    if effective_model:
        console.print(f"[dim]Model: {effective_model}[/dim]")
    if allowed_tools:
        console.print(f"[dim]Tools: {', '.join(allowed_tools)}[/dim]")
    if prompt:
        console.print(f"[dim]Prompt: {prompt}[/dim]")

    # Initialize repository and MCP server for single task execution
    repo = TaskHistoryRepository()
    process_id = secrets.token_hex(4)
    task_id = secrets.token_hex(4)

    # Create task log record (required for write_result FK constraint)
    start_time = datetime.now(UTC)
    task_log = TaskLog(
        task_id=task_id,
        process_id=process_id,
        executor_id=1,
        created_at=start_time.isoformat(),
        branch="main",
        worktree=str(Path.cwd()),
        main_repo=str(Path.cwd()),
        engine=resolved_engine.name,
        model=effective_model,
        task_name=task_name,
        prompt=prompt,
        prompt_hash=_hash_prompt(prompt),
        parent_id=None,
    )
    repo.create(task_log)

    mcp_bind_host = resolve_mcp_bind_host()
    mcp_server = WiggyMCPServer(repo=repo, process_id=process_id, host=mcp_bind_host)
    mcp_port: int | None = None
    try:
        mcp_port = mcp_server.start()
        console.print(f"[dim]MCP server started on {mcp_bind_host}:{mcp_port}[/dim]")
    except Exception:
        logger.warning(
            "MCP server failed to start, continuing without MCP",
            exc_info=True,
        )
        console.print(
            "[dim yellow]MCP server failed to start, "
            "continuing without MCP[/dim yellow]"
        )

    # Inject single-task MCP system prompt via extra_args
    if mcp_port is not None:
        mcp_prompt = _build_single_task_mcp_prompt()
        extra_args = (*extra_args, "--append-system-prompt", mcp_prompt)

    # When MCP is enabled and tools are restricted, add MCP tool names
    # so Claude Code's --allowedTools whitelist doesn't block MCP tools
    if mcp_port is not None and allowed_tools is not None:
        allowed_tools = allowed_tools + list(MCP_TOOL_NAMES)

    try:
        # Create executor with task settings - mount cwd for project files
        executors = get_executors(
            name="docker",
            count=1,
            model=effective_model,
            quiet=True,
            extra_args=extra_args,
            allowed_tools=allowed_tools,
            mount_cwd=True,
            mcp_port=mcp_port,
            git_author_name=git_author_name,
            git_author_email=git_author_email,
        )

        executor = executors[0]
        executor.set_task_id(task_id)
        executor.setup(resolved_engine, prompt)

        try:
            for msg in executor.run():
                # Simple output - in production, use Monitor
                if msg.content:
                    console.print(msg.content)
        finally:
            executor.teardown()

        # Complete task log with results
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

        # Post-step validation
        _check_task_result(repo, task_id, task_name)

        if exit_code != 0:
            console.print(f"[red]Task failed with exit code: {exit_code}[/red]")
            raise SystemExit(exit_code)

        console.print("[green]Task completed successfully.[/green]")
    finally:
        try:
            mcp_server.stop()
        except Exception:
            logger.warning("MCP server failed to stop cleanly", exc_info=True)


@task.command("create")
@click.option("--local", "-l", is_flag=True, help="Create task in local directory.")
def task_create(local: bool) -> None:
    """Create a new task via AI assistance."""
    # Check that create-task exists
    create_task_spec = get_task_by_name("create-task")
    if create_task_spec is None:
        console.print("[red]The 'create-task' task is not available.[/red]")
        console.print("[dim]Run 'wiggy init' to copy default tasks.[/dim]")
        raise SystemExit(1)

    # Get user input for what they want the task to do
    console.print("[bold]Create a new wiggy task[/bold]\n")
    goal = click.prompt("What do you want this task to achieve?")

    # Determine target directory and mount options
    if local:
        target_dir = get_local_tasks_path()
        container_target_dir = "/workspace/.wiggy/tasks"
        mount_cwd = True
        global_tasks_rw = False
    else:
        target_dir = get_global_tasks_path()
        container_target_dir = "/home/wiggy/.wiggy/tasks"
        mount_cwd = False
        global_tasks_rw = True

    target_dir.mkdir(parents=True, exist_ok=True)

    # Get existing tasks for context
    existing_tasks = get_all_tasks()
    tasks_context = _format_tasks_context(existing_tasks)

    # Build the main prompt with container paths
    main_prompt = f"""## Goal

{goal}

## Target Directory

Create the new task files in: {container_target_dir}

## Existing Tasks (for reference)

{tasks_context}
"""

    # Resolve engine
    resolved_engine = resolve_engine(None)
    if resolved_engine is None:
        raise SystemExit(1)

    # Build allowed_tools from create-task spec
    allowed_tools: list[str] | None = None
    if create_task_spec.tools and create_task_spec.tools != ("*",):
        allowed_tools = list(create_task_spec.tools)

    # Build extra args for --append-system-prompt
    extra_args: tuple[str, ...] = ()
    if create_task_spec.source:
        prompt_path = create_task_spec.source / "prompt.md"
        if prompt_path.exists():
            container_prompt_path = "/home/wiggy/.wiggy/tasks/create-task/prompt.md"
            extra_args = ("--append-system-prompt", container_prompt_path)

    console.print("\n[bold green]Creating task with AI assistance...[/bold green]")
    console.print(f"[dim]Engine: {resolved_engine.name}[/dim]")
    console.print(f"[dim]Target: {target_dir}[/dim]")

    # Create executor with appropriate mount options
    executors = get_executors(
        name="docker",
        count=1,
        quiet=True,
        extra_args=extra_args,
        allowed_tools=allowed_tools,
        mount_cwd=mount_cwd,
        global_tasks_rw=global_tasks_rw,
    )

    executor = executors[0]
    executor.setup(resolved_engine, main_prompt)

    try:
        for msg in executor.run():
            if msg.content:
                console.print(msg.content)
    finally:
        executor.teardown()

    exit_code = executor.exit_code or 0
    if exit_code != 0:
        console.print(f"[red]Task creation failed with exit code: {exit_code}[/red]")
        raise SystemExit(exit_code)

    console.print("\n[green]Task created successfully![/green]")
    console.print("[dim]Run 'wiggy task list' to see available tasks.[/dim]")


def _get_process_source_label(spec: ProcessSpec) -> str:
    """Get a label indicating whether a process is from global or local."""
    if spec.source is None:
        return ""
    source_str = str(spec.source)
    if ".wiggy/processes" in source_str:
        if str(Path.cwd()) in source_str:
            return "(local)"
        return "(global)"
    return ""


@main.group(invoke_without_command=True)
@click.pass_context
def process(ctx: click.Context) -> None:
    """Manage and run processes."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@process.command("list")
@click.option("--verbose", "-v", is_flag=True, help="Show process details.")
def process_list(verbose: bool) -> None:
    """List available processes."""
    processes = get_all_processes()

    if not processes:
        console.print("[yellow]No processes found.[/yellow]")
        console.print(
            "[dim]Run 'wiggy init' to copy default processes "
            "to ~/.wiggy/processes/[/dim]"
        )
        return

    console.print("[bold]Available Processes:[/bold]\n")
    for name, spec in sorted(processes.items()):
        source_label = _get_process_source_label(spec)
        console.print(f"  [cyan]{name}[/cyan] {source_label}")
        if verbose:
            if spec.description:
                console.print(f"    {spec.description.strip()}")
            step_names = [step.task for step in spec.steps]
            chain = " -> ".join(step_names)
            console.print(f"    [dim]Steps: {chain}[/dim]")
            console.print()


@process.command("run")
@click.argument("name")
@click.option("--engine", "-e", help="AI engine to use.")
@click.option("--model", "-m", help="Model to use (overrides step/task defaults).")
@click.option("--prompt", "-p", help="Additional prompt/instructions for all steps.")
@click.option(
    "--worktree",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Path to existing git worktree to use.",
)
@click.option(
    "--worktree-root",
    type=click.Path(file_okay=False, path_type=Path),
    envvar="WIGGY_WORKTREE_ROOT",
    help="Root directory for auto-created worktrees.",
)
@click.option(
    "--push/--no-push",
    default=True,
    help="Push to remote after execution (default: push).",
)
@click.option(
    "--pr/--no-pr",
    default=True,
    help="Create PR after execution (default: create PR).",
)
@click.option(
    "--remote",
    default="origin",
    envvar="WIGGY_REMOTE",
    help="Git remote to push to (default: origin).",
)
@click.option(
    "--keep-worktree",
    is_flag=True,
    default=False,
    help="Keep worktree after execution (default: delete).",
)
@click.pass_context
def process_run(
    ctx: click.Context,
    name: str,
    engine: str | None,
    model: str | None,
    prompt: str | None,
    worktree: Path | None,
    worktree_root: Path | None,
    push: bool,
    pr: bool,
    remote: str,
    keep_worktree: bool,
) -> None:
    """Run a process by name."""
    # Load config and apply values for options not explicitly set on CLI
    config = load_config()

    def _from_cli(param_name: str) -> bool:
        source = ctx.get_parameter_source(param_name)
        return source == click.core.ParameterSource.COMMANDLINE

    if not _from_cli("engine") and config.engine:
        engine = config.engine
    if not _from_cli("model") and config.model:
        model = config.model
    if not _from_cli("worktree_root") and config.worktree_root:
        worktree_root = Path(config.worktree_root)
    if not _from_cli("push") and config.push is not None:
        push = config.push
    if not _from_cli("pr") and config.pr is not None:
        pr = config.pr
    if not _from_cli("remote") and config.remote:
        remote = config.remote
    if not _from_cli("keep_worktree") and config.keep_worktree is not None:
        keep_worktree = config.keep_worktree

    spec = get_process_by_name(name)
    if spec is None:
        console.print(f"[red]Unknown process: {name}[/red]")
        console.print("[dim]Run 'wiggy process list' to see available processes.[/dim]")
        raise SystemExit(1)

    # Validate all referenced tasks exist upfront
    missing_tasks: list[str] = []
    for step in spec.steps:
        if get_task_by_name(step.task) is None:
            missing_tasks.append(step.task)

    if missing_tasks:
        console.print("[red]Process references missing tasks:[/red]")
        for task_name in missing_tasks:
            console.print(f"  - {task_name}")
        console.print("[dim]Run 'wiggy task list' to see available tasks.[/dim]")
        raise SystemExit(1)

    # Git worktree setup
    worktree_info: WorktreeInfo | None = None
    wt_manager: WorktreeManager | None = None

    try:
        wt_manager = WorktreeManager()

        if worktree:
            worktree_info = wt_manager.use_existing_worktree(worktree)
            console.print(f"[dim]Using existing worktree: {worktree_info.path}[/dim]")
            console.print(f"[dim]Branch: {worktree_info.branch}[/dim]")
        else:
            worktree_info = wt_manager.create_worktree(worktree_root=worktree_root)
            console.print(f"[dim]Created worktree: {worktree_info.path}[/dim]")
            console.print(f"[dim]Branch: {worktree_info.branch}[/dim]")

    except NotAGitRepoError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("[red]wiggy requires a git repository to run.[/red]")
        raise SystemExit(1) from None
    except WorktreeError as e:
        console.print(f"[red]Worktree error: {e}[/red]")
        raise SystemExit(1) from None

    # Resolve git author identity for Docker containers
    git_author_name, git_author_email = resolve_git_author(config)

    # Create monitor for the process
    # Use engine name directly for display - actual resolution happens in run_process
    step_names = [step.task for step in spec.steps]
    process_monitor = Monitor(
        engine or "auto",
        executor_count=1,
        model=model,
        process_name=name,
        step_names=step_names,
    )

    start_time = datetime.now(UTC)
    process_monitor.start()
    try:
        process_run_result = run_process(
            process_spec=spec,
            engine_name=engine,
            model_override=model,
            prompt=prompt,
            worktree_info=worktree_info,
            git_author_name=git_author_name,
            git_author_email=git_author_email,
            config=config,
            monitor=process_monitor,
        )
    except Exception:
        # Cleanup worktree on unexpected error
        if worktree_info and not keep_worktree and wt_manager and not worktree:
            console.print(f"[dim]Removing worktree: {worktree_info.path}[/dim]")
            try:
                wt_manager.remove_worktree(worktree_info, force=True)
            except WorktreeError as wt_err:
                console.print(
                    f"[yellow]Failed to remove worktree: {wt_err}[/yellow]"
                )
        raise
    finally:
        process_monitor.stop()
    end_time = datetime.now(UTC)

    # Print summary
    total_steps = len(process_run_result.steps)
    completed = len(process_run_result.results)
    passed = sum(1 for r in process_run_result.results if r.success)
    failed = sum(1 for r in process_run_result.results if not r.success)

    duration = end_time - start_time
    total_seconds = int(duration.total_seconds())
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    duration_str = f"{minutes}m {seconds:02d}s"

    console.print()
    console.print(f"[bold]Process: {name}[/bold]")
    console.print(f"Steps: {completed}/{total_steps} completed")
    if failed > 0:
        console.print(f"Passed: {passed}, Failed: {failed}")
    console.print(f"Duration: {duration_str}")

    any_failed = any(not r.success for r in process_run_result.results)
    if any_failed:
        console.print("Status: [red]FAILED[/red]")
        console.print(
            "[yellow]Process failed - skipping push/PR, keeping worktree[/yellow]"
        )
        raise SystemExit(1)
    else:
        console.print("Status: [green]SUCCESS[/green]")

    # Post-execution git operations
    if worktree_info is not None:
        git_ops = GitOperations(worktree_info)

        if push and git_ops.has_commits():
            console.print(
                f"[dim]Pushing {worktree_info.branch} to {remote}...[/dim]"
            )
            if git_ops.push_to_remote(remote):
                console.print(
                    f"[green]Pushed {worktree_info.branch} to {remote}[/green]"
                )
            else:
                console.print(
                    f"[yellow]Failed to push {worktree_info.branch}[/yellow]"
                )

        if pr and push and git_ops.has_commits():
            console.print(
                f"[dim]Creating pull request for {worktree_info.branch}...[/dim]"
            )
            pr_body = process_run_result.pr_body
            if not pr_body:
                # Fallback: build body from commit messages
                commits = git_ops.get_commit_messages()
                if commits:
                    pr_body = "\n".join(f"- {msg}" for msg in commits)
            pr_url = git_ops.create_pull_request(
                body=pr_body,
            )
            if pr_url:
                console.print(f"[green]PR created: {pr_url}[/green]")
            else:
                console.print(
                    "[yellow]Failed to create PR (is gh CLI installed?)[/yellow]"
                )

        # Cleanup worktree unless --keep-worktree or using existing worktree
        if not keep_worktree and wt_manager and not worktree:
            console.print(f"[dim]Removing worktree: {worktree_info.path}[/dim]")
            try:
                wt_manager.remove_worktree(worktree_info, force=True)
            except WorktreeError as e:
                console.print(
                    f"[yellow]Failed to remove worktree: {e}[/yellow]"
                )


@process.command("create")
@click.option("--local", "-l", is_flag=True, help="Create process in local directory.")
def process_create(local: bool) -> None:
    """Create a new process via AI assistance."""
    # Check that create-task exists (reuse same AI-assisted creation approach)
    create_task_spec = get_task_by_name("create-task")
    if create_task_spec is None:
        console.print("[red]The 'create-task' task is not available.[/red]")
        console.print("[dim]Run 'wiggy init' to copy default tasks.[/dim]")
        raise SystemExit(1)

    # Get user input
    console.print("[bold]Create a new wiggy process[/bold]\n")
    goal = click.prompt("What should this process achieve?")

    # Determine target directory and mount options
    if local:
        target_dir = get_local_processes_path()
        container_target_dir = "/workspace/.wiggy/processes"
        mount_cwd = True
        global_tasks_rw = False
    else:
        target_dir = get_global_processes_path()
        container_target_dir = "/home/wiggy/.wiggy/processes"
        mount_cwd = False
        global_tasks_rw = True

    target_dir.mkdir(parents=True, exist_ok=True)

    # Get existing tasks and processes for context
    existing_tasks = get_all_tasks()
    tasks_context = _format_tasks_context(existing_tasks)

    existing_processes = get_all_processes()
    processes_context = _format_processes_context(existing_processes)

    # Build the main prompt
    main_prompt = f"""## Goal

{goal}

## Target Directory

Create the new process files in: {container_target_dir}
Each process lives in its own subdirectory with a process.yaml file.

## Process YAML Format

```yaml
name: process-name
description: What this process does
steps:
  - task: task-name
    prompt: Optional step-specific prompt
  - task: another-task
```

## Available Tasks

{tasks_context}

## Existing Processes (for reference)

{processes_context}
"""

    # Resolve engine
    resolved_engine = resolve_engine(None)
    if resolved_engine is None:
        raise SystemExit(1)

    # Build allowed_tools from create-task spec
    allowed_tools: list[str] | None = None
    if create_task_spec.tools and create_task_spec.tools != ("*",):
        allowed_tools = list(create_task_spec.tools)

    # Build extra args for --append-system-prompt
    extra_args: tuple[str, ...] = ()
    if create_task_spec.source:
        prompt_path = create_task_spec.source / "prompt.md"
        if prompt_path.exists():
            container_prompt_path = "/home/wiggy/.wiggy/tasks/create-task/prompt.md"
            extra_args = ("--append-system-prompt", container_prompt_path)

    console.print("\n[bold green]Creating process with AI assistance...[/bold green]")
    console.print(f"[dim]Engine: {resolved_engine.name}[/dim]")
    console.print(f"[dim]Target: {target_dir}[/dim]")

    # Create executor
    executors = get_executors(
        name="docker",
        count=1,
        quiet=True,
        extra_args=extra_args,
        allowed_tools=allowed_tools,
        mount_cwd=mount_cwd,
        global_tasks_rw=global_tasks_rw,
    )

    executor_instance = executors[0]
    executor_instance.setup(resolved_engine, main_prompt)

    try:
        for msg in executor_instance.run():
            if msg.content:
                console.print(msg.content)
    finally:
        executor_instance.teardown()

    exit_code = executor_instance.exit_code or 0
    if exit_code != 0:
        console.print(f"[red]Process creation failed with exit code: {exit_code}[/red]")
        raise SystemExit(exit_code)

    console.print("\n[green]Process created successfully![/green]")
    console.print("[dim]Run 'wiggy process list' to see available processes.[/dim]")


def _format_processes_context(processes: dict[str, ProcessSpec]) -> str:
    """Format processes as context for AI prompts."""
    if not processes:
        return "No existing processes."
    lines: list[str] = []
    for name, spec in sorted(processes.items()):
        step_chain = " -> ".join(step.task for step in spec.steps)
        lines.append(f"### {name}")
        if spec.description:
            lines.append(spec.description.strip())
        lines.append(f"Steps: {step_chain}")
        lines.append("")
    return "\n".join(lines)
