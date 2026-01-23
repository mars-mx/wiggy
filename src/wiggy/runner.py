"""Runner for the wiggy loop with engine validation."""

from wiggy.console import console
from wiggy.engines import Engine, ENGINES, get_available_engines, get_engine_by_name


def resolve_engine(engine_name: str | None) -> Engine | None:
    """Resolve which engine to use.

    Returns the engine if valid, None if validation fails (errors printed).

    Logic:
    - If engine_name provided: validate it exists and is installed
    - If not provided: auto-select if exactly one engine is installed
    """
    if engine_name:
        # User specified an engine
        engine = get_engine_by_name(engine_name)
        if engine is None:
            console.print(f"[red]Unknown engine: {engine_name}[/red]")
            console.print("Available engines: " + ", ".join(e.cli_command for e in ENGINES))
            return None
        if not engine.is_installed():
            console.print(f"[red]Engine '{engine.name}' is not installed.[/red]")
            console.print(f"Install: {engine.install_info}")
            return None
        return engine

    # No engine specified - try auto-detection
    available = get_available_engines()

    if len(available) == 0:
        console.print("[red]No engines installed.[/red]")
        console.print("Install at least one engine:")
        for engine in ENGINES:
            console.print(f"  - {engine.name}: {engine.install_info}")
        return None

    if len(available) == 1:
        engine = available[0]
        console.print(f"[dim]Auto-selected engine: {engine.name}[/dim]")
        return engine

    # Multiple engines - user must choose
    console.print("[red]Multiple engines installed. Please specify one with --engine.[/red]")
    console.print("Available engines:")
    for engine in available:
        console.print(f"  - {engine.cli_command} ({engine.name})")
    return None
