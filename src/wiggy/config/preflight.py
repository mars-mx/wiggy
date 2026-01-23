"""Preflight checks to validate environment."""

import docker
from docker.errors import DockerException

from wiggy.console import console
from wiggy.engines import ENGINES, get_available_engines


def check_docker() -> bool:
    """Validate Docker daemon is running and accessible."""
    try:
        client = docker.from_env()
        client.ping()
        console.print("[green]✓[/green] Docker daemon is running")
    except DockerException as e:
        console.print(f"[red]✗[/red] Cannot connect to Docker: {e}")
        return False

    try:
        version = client.version()
        console.print(f"[green]✓[/green] Docker version: {version['Version']}")
    except DockerException as e:
        console.print(f"[red]✗[/red] Cannot get Docker version: {e}")
        return False

    return True


def check_engines() -> bool:
    """Check for installed AI coding engines."""
    console.print("\n[bold]AI Coding Engines:[/bold]")

    for engine in ENGINES:
        if engine.is_installed():
            console.print(
                f"  [green]✓[/green] {engine.name} ([cyan]{engine.cli_command}[/cyan])"
            )
        else:
            console.print(
                f"  [dim]✗[/dim] {engine.name} - [dim]{engine.install_info}[/dim]"
            )

    available = get_available_engines()
    if not available:
        console.print("\n[yellow]⚠[/yellow] No AI coding engines detected.")
        console.print("[dim]Install at least one engine to use wiggy.[/dim]")
        return False

    console.print(f"\n[green]✓[/green] {len(available)} engine(s) available")
    return True


CHECKS = [
    check_docker,
    check_engines,
]


def run_all_checks() -> bool:
    """Run all preflight checks."""
    console.print("[bold]Running preflight checks...[/bold]\n")

    results = [check() for check in CHECKS]
    all_passed = all(results)

    if all_passed:
        console.print("\n[bold green]All preflight checks passed![/bold green]")
    else:
        console.print("\n[bold red]Some preflight checks failed.[/bold red]")

    return all_passed
