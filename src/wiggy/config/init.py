"""Initialization logic for wiggy directory structure."""

import shutil
from pathlib import Path

from wiggy.processes.loader import discover_process_dirs, get_package_processes_path
from wiggy.tasks.loader import discover_task_dirs, get_package_tasks_path
from wiggy.templates.loader import discover_template_dirs, get_package_templates_path


def copy_default_tasks(local: bool = False) -> list[str]:
    """Copy default tasks from package to task directory.

    Args:
        local: If True, copy to ./.wiggy/tasks/ (project-local).
               If False, copy to ~/.wiggy/tasks/ (global, default).

    Returns:
        List of task names that were copied.
    """
    package_tasks_path = get_package_tasks_path()

    if local:
        target = Path.cwd() / ".wiggy" / "tasks"
    else:
        target = Path.home() / ".wiggy" / "tasks"

    target.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for task_name, task_dir in discover_task_dirs(package_tasks_path).items():
        dest = target / task_name
        if not dest.exists():
            shutil.copytree(task_dir, dest)
            copied.append(task_name)

    return copied


def copy_default_processes(local: bool = False) -> list[str]:
    """Copy default processes from package to processes directory.

    Args:
        local: If True, copy to ./.wiggy/processes/ (project-local).
               If False, copy to ~/.wiggy/processes/ (global, default).

    Returns:
        List of process names that were copied.
    """
    package_processes_path = get_package_processes_path()

    if local:
        target = Path.cwd() / ".wiggy" / "processes"
    else:
        target = Path.home() / ".wiggy" / "processes"

    target.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for process_name, process_dir in discover_process_dirs(
        package_processes_path
    ).items():
        dest = target / process_name
        if not dest.exists():
            shutil.copytree(process_dir, dest)
            copied.append(process_name)

    return copied


def copy_default_templates(local: bool = False) -> list[str]:
    """Copy default templates from package to templates directory.

    Args:
        local: If True, copy to ./.wiggy/templates/ (project-local).
               If False, copy to ~/.wiggy/templates/ (global, default).

    Returns:
        List of template names that were copied.
    """
    package_templates_path = get_package_templates_path()

    if local:
        target = Path.cwd() / ".wiggy" / "templates"
    else:
        target = Path.home() / ".wiggy" / "templates"

    target.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for template_name, template_dir in discover_template_dirs(
        package_templates_path
    ).items():
        dest = target / template_name
        if not dest.exists():
            shutil.copytree(template_dir, dest)
            copied.append(template_name)

    return copied


def ensure_wiggy_dir() -> None:
    """Create .wiggy directory structure in current working directory.

    Creates:
        .wiggy/
        .wiggy/logs/
        .wiggy/.gitignore (with logs/ ignored)
    """
    wiggy_dir = Path.cwd() / ".wiggy"
    logs_dir = wiggy_dir / "logs"
    gitignore_path = wiggy_dir / ".gitignore"

    # Create directories (parents=True creates .wiggy if needed)
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Create .gitignore if it doesn't exist
    if not gitignore_path.exists():
        gitignore_path.write_text("logs/\n")


def ensure_home_wiggy_dir() -> Path:
    """Create ~/.wiggy directory if it doesn't exist.

    Returns the path to the home wiggy directory.
    """
    home_wiggy = Path.home() / ".wiggy"
    home_wiggy.mkdir(parents=True, exist_ok=True)
    return home_wiggy
