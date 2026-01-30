"""Process loading and discovery."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from wiggy.processes.base import ProcessSpec

# Constants
PROCESS_DIRNAME = "processes"
PROCESS_YAML = "process.yaml"


def get_package_processes_path() -> Path:
    """Get path to package-bundled default processes."""
    return Path(__file__).parent / "default"


def get_global_processes_path() -> Path:
    """Get path to global user processes: ~/.wiggy/processes/."""
    return Path.home() / ".wiggy" / PROCESS_DIRNAME


def get_local_processes_path() -> Path:
    """Get path to project-specific processes: ./.wiggy/processes/."""
    return Path.cwd() / ".wiggy" / PROCESS_DIRNAME


def discover_process_dirs(base_path: Path) -> dict[str, Path]:
    """Discover process directories within a base path.

    Returns dict mapping process name -> process directory path.
    Only includes directories containing process.yaml.
    """
    processes: dict[str, Path] = {}
    if not base_path.exists():
        return processes

    for item in base_path.iterdir():
        if item.is_dir():
            process_yaml = item / PROCESS_YAML
            if process_yaml.exists():
                processes[item.name] = item

    return processes


def load_process_from_dir(process_dir: Path) -> ProcessSpec | None:
    """Load a ProcessSpec from a process directory.

    Returns None if process.yaml is missing or invalid.
    """
    process_yaml = process_dir / PROCESS_YAML
    if not process_yaml.exists():
        return None

    try:
        with process_yaml.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if not isinstance(data, dict):
                return None
    except yaml.YAMLError:
        return None

    return ProcessSpec.from_dict(data, source=process_dir)


def get_all_processes() -> dict[str, ProcessSpec]:
    """Discover and load all processes from filesystem locations.

    Resolution order (later wins for same name):
    1. Global (~/.wiggy/processes/)
    2. Project (./.wiggy/processes/)

    Returns dict mapping process name -> ProcessSpec.
    """
    processes: dict[str, ProcessSpec] = {}

    # 1. Global processes (lower priority)
    global_processes = discover_process_dirs(get_global_processes_path())
    for name, process_dir in global_processes.items():
        spec = load_process_from_dir(process_dir)
        if spec:
            processes[name] = spec

    # 2. Local/project processes (highest priority, overrides global)
    local_processes = discover_process_dirs(get_local_processes_path())
    for name, process_dir in local_processes.items():
        spec = load_process_from_dir(process_dir)
        if spec:
            processes[name] = spec

    return processes


def get_process_by_name(name: str) -> ProcessSpec | None:
    """Get a specific process by name, using resolution order.

    Checks local first, then global.
    """
    # Check local first (highest priority)
    local_path = get_local_processes_path() / name
    if local_path.exists():
        spec = load_process_from_dir(local_path)
        if spec:
            return spec

    # Check global
    global_path = get_global_processes_path() / name
    if global_path.exists():
        spec = load_process_from_dir(global_path)
        if spec:
            return spec

    return None


def copy_default_processes_to_user(overwrite: bool = False) -> list[str]:
    """Copy package default processes to user's global processes directory.

    Args:
        overwrite: If True, overwrite existing processes. If False, skip existing.

    Returns:
        List of process names that were copied.
    """
    package_path = get_package_processes_path()
    global_path = get_global_processes_path()
    global_path.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []

    for process_name, process_dir in discover_process_dirs(package_path).items():
        dest_dir = global_path / process_name

        if dest_dir.exists() and not overwrite:
            continue

        if dest_dir.exists():
            shutil.rmtree(dest_dir)

        shutil.copytree(process_dir, dest_dir)
        copied.append(process_name)

    return copied
