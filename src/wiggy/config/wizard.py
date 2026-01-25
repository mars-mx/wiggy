"""Interactive configuration wizard."""

import click

from wiggy.config.loader import (
    get_home_config_path,
    get_local_config_path,
    home_config_exists,
    load_config,
    save_config,
)
from wiggy.config.schema import ExecutorType, WiggyConfig
from wiggy.console import console
from wiggy.engines import ENGINES, get_available_engines


def run_home_wizard() -> WiggyConfig:
    """Run interactive wizard to create global config.

    Returns the created WiggyConfig.
    """
    console.print("\n[bold]Let's create your global configuration.[/bold]\n")

    config = WiggyConfig()

    # 1. Default Engine
    config.engine = _wizard_select_engine()

    # 2. Default Executor
    config.executor = _wizard_select_executor()

    # 3. Parallel Instances
    config.parallel = _wizard_configure_parallel()

    # 4. Git Push
    config.push = click.confirm("Push to remote after execution?", default=True)

    # 5. Create PR
    config.pr = click.confirm("Create pull request after execution?", default=True)

    # 6. Git Remote
    config.remote = click.prompt("Git remote name", default="origin")

    # Review
    console.print("\n[bold]Review Configuration:[/bold]")
    for key, value in config.to_dict().items():
        console.print(f"  {key}: {value}")

    if click.confirm("\nSave configuration?", default=True):
        path = get_home_config_path()
        save_config(config, path)
        console.print(f"\n[green]Configuration saved to {path}[/green]")
        console.print(
            "\nRun [cyan]wiggy init[/cyan] again in a project to create "
            "project-specific overrides."
        )
    else:
        console.print("\n[yellow]Configuration not saved.[/yellow]")

    return config


def run_local_wizard(home_config: WiggyConfig) -> WiggyConfig:
    """Run interactive wizard to create local project config overrides.

    Args:
        home_config: The current global configuration to show as defaults.

    Returns the created WiggyConfig (only contains overridden values).
    """
    console.print("\n[bold]Create local project configuration overrides.[/bold]")
    console.print("[dim]Only values you choose to override will be saved.[/dim]\n")

    config = WiggyConfig()

    # Engine
    current_engine = home_config.engine or "(not set)"
    if click.confirm(f"Override engine? (current: {current_engine})", default=False):
        config.engine = _wizard_select_engine()

    # Executor
    current_executor = home_config.executor or "docker"
    if click.confirm(
        f"Override executor? (current: {current_executor})", default=False
    ):
        config.executor = _wizard_select_executor()

    # Parallel
    current_parallel = home_config.parallel or 1
    if click.confirm(
        f"Override parallel instances? (current: {current_parallel})", default=False
    ):
        config.parallel = _wizard_configure_parallel()

    # Model
    current_model = home_config.model or "(not set)"
    if click.confirm(f"Override model? (current: {current_model})", default=False):
        config.model = click.prompt("Model name", default="")
        if not config.model:
            config.model = None

    # Image
    current_image = home_config.image or "(not set)"
    if click.confirm(
        f"Override Docker image? (current: {current_image})", default=False
    ):
        config.image = click.prompt("Docker image", default="")
        if not config.image:
            config.image = None

    # Push
    current_push = home_config.push if home_config.push is not None else True
    prompt = f"Override push setting? (current: {current_push})"
    if click.confirm(prompt, default=False):
        config.push = click.confirm("Push to remote after execution?", default=True)

    # PR
    current_pr = home_config.pr if home_config.pr is not None else True
    if click.confirm(f"Override PR setting? (current: {current_pr})", default=False):
        config.pr = click.confirm("Create pull request after execution?", default=True)

    # Remote
    current_remote = home_config.remote or "origin"
    if click.confirm(
        f"Override git remote? (current: {current_remote})", default=False
    ):
        config.remote = click.prompt("Git remote name", default="origin")

    # Review
    overrides = config.to_dict()
    if overrides:
        console.print("\n[bold]Local Configuration Overrides:[/bold]")
        for key, value in overrides.items():
            console.print(f"  {key}: {value}")

        if click.confirm("\nSave configuration?", default=True):
            path = get_local_config_path()
            save_config(config, path)
            console.print(f"\n[green]Configuration saved to {path}[/green]")
        else:
            console.print("\n[yellow]Configuration not saved.[/yellow]")
    else:
        console.print("\n[yellow]No overrides selected. No file created.[/yellow]")

    return config


def _wizard_select_engine() -> str | None:
    """Prompt user to select default engine."""
    available = get_available_engines()

    console.print("[bold]Default AI Engine[/bold]")

    if available:
        console.print("  Available (installed):")
        for i, engine in enumerate(available, 1):
            console.print(f"    {i}. {engine.cli_command} ({engine.name})")
    else:
        console.print("  [yellow]No engines currently installed.[/yellow]")

    missing = [e for e in ENGINES if e not in available]
    if missing:
        console.print("  Not installed:")
        for engine in missing:
            console.print(f"    - {engine.cli_command} ({engine.name})")

    console.print("  [dim]Enter engine name or leave blank for auto-detect.[/dim]")

    engine_name = click.prompt("Engine", default="", show_default=False)
    return engine_name if engine_name else None


def _wizard_select_executor() -> ExecutorType:
    """Prompt user to select default executor."""
    console.print("\n[bold]Default Executor[/bold]")
    console.print("  1. docker (recommended - isolated execution)")
    console.print("  2. shell (local execution)")

    choice: str = click.prompt("Select executor", default="1")
    if choice == "2" or choice.lower() == "shell":
        return "shell"
    return "docker"


def _wizard_configure_parallel() -> int:
    """Prompt for default parallel instances."""
    result: int = click.prompt("\nDefault parallel instances", default=1, type=int)
    return result


def show_current_config() -> None:
    """Display the current effective configuration."""
    config = load_config()
    console.print("\n[bold]Current Effective Configuration:[/bold]")
    console.print(f"  [dim]Global: {get_home_config_path()}[/dim]")
    console.print(f"  [dim]Local: {get_local_config_path()}[/dim]")
    console.print()

    data = config.to_dict()
    if data:
        for key, value in data.items():
            console.print(f"  {key}: {value}")
    else:
        console.print("  [dim](using built-in defaults)[/dim]")

    # Show source info
    console.print()
    if home_config_exists():
        console.print("  [green]Global config: exists[/green]")
    else:
        console.print("  [dim]Global config: not found[/dim]")

    from wiggy.config.loader import local_config_exists

    if local_config_exists():
        console.print("  [green]Local config: exists[/green]")
    else:
        console.print("  [dim]Local config: not found[/dim]")
