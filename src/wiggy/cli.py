"""Command-line interface for wiggy."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue

import click

from wiggy import __version__
from wiggy.config.init import ensure_wiggy_dir
from wiggy.config.preflight import run_all_checks
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
from wiggy.monitor import Monitor
from wiggy.parsers.messages import ParsedMessage
from wiggy.runner import resolve_engine


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
def run(
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
) -> None:
    """Run the wiggy loop."""
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

    # Create monitor for real-time status display
    monitor = Monitor(resolved_engine.name, parallel, model=model)

    # Queue for messages from executor threads: (executor_id, message or None for done)
    queue: Queue[tuple[int, ParsedMessage | None]] = Queue()

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

            # Collect exit codes
            exit_codes = [f.result() for f in futures]

    finally:
        monitor.stop()

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
