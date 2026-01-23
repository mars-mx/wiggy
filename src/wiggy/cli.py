"""Command-line interface for wiggy."""

import click

from wiggy import __version__
from wiggy.config.preflight import run_all_checks
from wiggy.console import console
from wiggy.executors import DEFAULT_EXECUTOR, EXECUTORS
from wiggy.executors.base import Executor
from wiggy.executors.docker import DockerExecutor
from wiggy.executors.shell import ShellExecutor
from wiggy.monitor import Monitor
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

    # Create executor instance
    exec_instance: Executor
    if executor == "docker":
        exec_instance = DockerExecutor(image_override=image, model_override=model)
    else:
        exec_instance = ShellExecutor(model_override=model)

    # Create monitor for real-time status display
    monitor = Monitor(resolved_engine.name, parallel, model=model)

    try:
        exec_instance.setup(resolved_engine, prompt)
        monitor.start()

        for message in exec_instance.run():
            monitor.update(1, message)  # executor_id = 1 for single executor

    finally:
        monitor.stop()
        exec_instance.teardown()

    if exec_instance.exit_code != 0:
        raise SystemExit(exec_instance.exit_code or 1)


@main.command()
def preflight() -> None:
    """Validate environment is ready (Docker, etc.)."""
    if not run_all_checks():
        raise SystemExit(1)
