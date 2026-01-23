"""Command-line interface for wiggy."""

import click

from wiggy import __version__
from wiggy.config.preflight import run_all_checks
from wiggy.console import console
from wiggy.executors import DEFAULT_EXECUTOR, EXECUTORS
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
def run(engine: str | None, executor: str, image: str | None, parallel: int) -> None:
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
    console.print("[dim]Not implemented yet.[/dim]")


@main.command()
def preflight() -> None:
    """Validate environment is ready (Docker, etc.)."""
    if not run_all_checks():
        raise SystemExit(1)
