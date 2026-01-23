"""Command-line interface for wiggy."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue

import click

from wiggy import __version__
from wiggy.config.init import ensure_wiggy_dir
from wiggy.config.preflight import run_all_checks
from wiggy.console import console
from wiggy.executors import DEFAULT_EXECUTOR, EXECUTORS, get_executors
from wiggy.executors.base import Executor
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
def run(
    prompt: str | None,
    engine: str | None,
    executor: str,
    image: str | None,
    parallel: int,
    model: str | None,
) -> None:
    """Run the wiggy loop."""
    resolved_engine = resolve_engine(engine)
    if resolved_engine is None:
        raise SystemExit(1)

    # Validate --image is only used with docker executor
    if image and executor != "docker":
        console.print("[red]--image can only be used with docker executor[/red]")
        raise SystemExit(1)

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

    # Create executor instances
    executors = get_executors(
        name=executor,
        count=parallel,
        image=image,
        model=model,
        quiet=True,
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
    failed = [code for code in exit_codes if code != 0]
    if failed:
        raise SystemExit(failed[0] or 1)


@main.command()
def preflight() -> None:
    """Validate environment is ready (Docker, etc.)."""
    if not run_all_checks():
        raise SystemExit(1)
