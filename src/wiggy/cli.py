"""Command-line interface for wiggy."""

import hashlib
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from queue import Queue

import click

from wiggy import __version__
from wiggy.config.init import ensure_wiggy_dir
from wiggy.config.loader import (
    get_home_config_path,
    home_config_exists,
    load_config,
    local_config_exists,
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
from wiggy.monitor import Monitor
from wiggy.parsers.messages import MessageType, ParsedMessage
from wiggy.runner import resolve_engine


def _hash_prompt(prompt: str | None) -> str | None:
    """Generate SHA256[:16] hash of prompt for deduplication."""
    if prompt is None:
        return None
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


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
    "--engine", "-e",
    help="AI engine to use (e.g., claude, opencode, codex).",
)
@click.option(
    "--executor", "-x",
    type=click.Choice(list(EXECUTORS.keys())),
    default=DEFAULT_EXECUTOR,
    help="Executor to use.",
)
@click.option(
    "--image", "-i",
    help="Docker image to use (overrides engine default). Only for docker executor.",
)
@click.option(
    "--parallel", "-p",
    type=int,
    default=1,
    help="Number of executor instances to spawn in parallel.",
)
@click.option(
    "--model", "-m",
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

    # Create executor instances with worktree info
    executors = get_executors(
        name=executor,
        count=parallel,
        image=image,
        model=model,
        quiet=True,
        worktree_infos=worktree_infos if worktree_infos else None,
    )

    # Generate process_id and task_ids, create task log records
    process_id = secrets.token_hex(4)
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
    monitor = Monitor(resolved_engine.name, parallel, model=model)

    # Queue for messages from executor threads: (executor_id, message or None for done)
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
                                repo.update_session_id(exec_task_id, engine_session_id)

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

    # Check for failures
    any_failed = any(code != 0 for code in exit_codes)

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
                        console.print(f"[green]Pushed {info.branch} to {remote}[/green]")
                    else:
                        console.print(f"[yellow]Failed to push {info.branch}[/yellow]")

                if pr and push and git_ops.has_commits():
                    console.print(f"[dim]Creating pull request for {info.branch}...[/dim]")
                    pr_url = git_ops.create_pull_request()
                    if pr_url:
                        console.print(f"[green]PR created: {pr_url}[/green]")
                    else:
                        console.print(
                            "[yellow]Failed to create PR (is gh CLI installed?)[/yellow]"
                        )

            # Cleanup worktrees unless --keep-worktree (only on success)
            if not keep_worktree and wt_manager:
                for info in unique_infos:
                    console.print(f"[dim]Removing worktree: {info.path}[/dim]")
                    try:
                        wt_manager.remove_worktree(info, force=True)
                    except WorktreeError as e:
                        console.print(f"[yellow]Failed to remove worktree: {e}[/yellow]")

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
            console.print(f"[dim]No tasks older than {older_than} days to clean up.[/dim]")


@main.command()
@click.option(
    "--limit", "-n",
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
        status = "[green]✓[/green]" if task.success else (
            "[red]✗[/red]" if task.success is False else "[yellow]?[/yellow]"
        )
        console.print(f"  {status} [cyan]{task.task_id}[/cyan] | {task.branch}")
        console.print(f"      Engine: {task.engine} | Created: {task.created_at[:19]}")
        if task.prompt:
            prompt_preview = task.prompt[:50] + "..." if len(task.prompt) > 50 else task.prompt
            console.print(f"      Prompt: {prompt_preview}")
        console.print()


@main.command()
@click.option(
    "--global", "-g",
    "global_config",
    is_flag=True,
    help="Create or update global config (~/.wiggy/config.yaml).",
)
@click.option(
    "--local", "-l",
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
            console.print(
                f"[yellow]Global config already exists at {get_home_config_path()}[/yellow]"
            )
            if click.confirm("Overwrite with new configuration?", default=False):
                run_home_wizard()
            else:
                console.print("\nNo changes made.")
        else:
            run_home_wizard()
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
        return

    # No flags: interactive flow
    if not home_config_exists():
        # First time user flow
        console.print(
            f"[yellow]No global configuration found at {get_home_config_path()}[/yellow]"
        )
        if click.confirm("Is this your first time using wiggy?", default=True):
            run_home_wizard()
        else:
            console.print(
                "\nTo create a global config, run [cyan]wiggy init --global[/cyan]."
            )
    else:
        # Existing user flow
        console.print(
            f"[green]Global configuration found at {get_home_config_path()}[/green]"
        )
        console.print(
            "[dim]Use 'wiggy init --global' to update global settings.[/dim]"
        )

        if local_config_exists():
            console.print(
                "\n[dim]Local project config already exists at .wiggy/config.yaml[/dim]"
            )
            if click.confirm("Would you like to update it?", default=False):
                home_cfg = load_config()
                run_local_wizard(home_cfg)
            else:
                console.print("\nNo changes made.")
        else:
            if click.confirm(
                "\nWould you like to create project-specific overrides?", default=False
            ):
                home_cfg = load_config()
                run_local_wizard(home_cfg)
            else:
                console.print("\nUsing global configuration. No changes made.")
