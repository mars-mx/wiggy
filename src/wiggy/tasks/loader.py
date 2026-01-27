"""Task loading and discovery."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from wiggy.tasks.base import TaskSpec

# Constants
TASK_DIRNAME = "tasks"
TASK_YAML = "task.yaml"


def get_package_tasks_path() -> Path:
    """Get path to package-bundled default tasks."""
    return Path(__file__).parent / "default"


def get_global_tasks_path() -> Path:
    """Get path to global user tasks: ~/.wiggy/tasks/."""
    return Path.home() / ".wiggy" / TASK_DIRNAME


def get_local_tasks_path() -> Path:
    """Get path to project-specific tasks: ./.wiggy/tasks/."""
    return Path.cwd() / ".wiggy" / TASK_DIRNAME


def get_task_search_paths() -> list[Path]:
    """Return task search paths in priority order (highest first).

    Resolution order:
    1. Local project tasks (./.wiggy/tasks/) - highest priority
    2. Global user tasks (~/.wiggy/tasks/)

    No package fallback at runtime - tasks must exist in one of these locations.
    """
    paths = []

    # Local project tasks (highest priority)
    local = get_local_tasks_path()
    if local.exists():
        paths.append(local)

    # Global user tasks
    global_tasks = get_global_tasks_path()
    if global_tasks.exists():
        paths.append(global_tasks)

    return paths


def discover_task_dirs(base_path: Path) -> dict[str, Path]:
    """Discover task directories within a base path.

    Returns dict mapping task name -> task directory path.
    Only includes directories containing task.yaml.
    """
    tasks: dict[str, Path] = {}
    if not base_path.exists():
        return tasks

    for item in base_path.iterdir():
        if item.is_dir():
            task_yaml = item / TASK_YAML
            if task_yaml.exists():
                tasks[item.name] = item

    return tasks


def load_markdown_files(task_dir: Path) -> str:
    """Load and combine all .md files in a task directory.

    Files are sorted alphabetically, allowing numbered prefixes
    (01_context.md, 02_guidelines.md) for explicit ordering.

    Returns combined content with double newlines between files.
    """
    md_files = sorted(task_dir.glob("*.md"))
    if not md_files:
        return ""

    contents: list[str] = []
    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8").strip()
        if content:
            contents.append(content)

    return "\n\n".join(contents)


def load_task_from_dir(task_dir: Path) -> TaskSpec | None:
    """Load a TaskSpec from a task directory.

    Returns None if task.yaml is missing or invalid.
    """
    task_yaml = task_dir / TASK_YAML
    if not task_yaml.exists():
        return None

    try:
        with task_yaml.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if not isinstance(data, dict):
                return None
    except yaml.YAMLError:
        return None

    # Create base spec from YAML
    spec = TaskSpec.from_dict(data, source=task_dir)

    # Load and combine markdown files
    prompt_template = load_markdown_files(task_dir)

    return spec.with_prompt(prompt_template)


def get_all_tasks() -> dict[str, TaskSpec]:
    """Discover and load all tasks from filesystem locations.

    Resolution order (later wins for same name):
    1. Global (~/.wiggy/tasks/)
    2. Project (./.wiggy/tasks/)

    No package fallback at runtime - run 'wiggy init' to copy default tasks.

    Returns dict mapping task name -> TaskSpec.
    """
    tasks: dict[str, TaskSpec] = {}

    # 1. Global tasks (lower priority)
    global_tasks = discover_task_dirs(get_global_tasks_path())
    for name, task_dir in global_tasks.items():
        spec = load_task_from_dir(task_dir)
        if spec:
            tasks[name] = spec

    # 2. Local/project tasks (highest priority, overrides global)
    local_tasks = discover_task_dirs(get_local_tasks_path())
    for name, task_dir in local_tasks.items():
        spec = load_task_from_dir(task_dir)
        if spec:
            tasks[name] = spec

    return tasks


def get_task_by_name(name: str) -> TaskSpec | None:
    """Get a specific task by name, using resolution order.

    Checks local first, then global. No package fallback at runtime.
    """
    # Check local first (highest priority)
    local_path = get_local_tasks_path() / name
    if local_path.exists():
        spec = load_task_from_dir(local_path)
        if spec:
            return spec

    # Check global
    global_path = get_global_tasks_path() / name
    if global_path.exists():
        spec = load_task_from_dir(global_path)
        if spec:
            return spec

    return None


def get_available_task_names() -> list[str]:
    """Get list of all available task names (from all locations)."""
    return sorted(get_all_tasks().keys())


def copy_default_tasks_to_user(overwrite: bool = False) -> list[str]:
    """Copy package default tasks to user's global tasks directory.

    This is called during 'wiggy init' to give users editable copies
    of the default tasks.

    Args:
        overwrite: If True, overwrite existing tasks. If False, skip existing.

    Returns:
        List of task names that were copied.
    """
    package_path = get_package_tasks_path()
    global_path = get_global_tasks_path()
    global_path.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []

    for task_name, task_dir in discover_task_dirs(package_path).items():
        dest_dir = global_path / task_name

        if dest_dir.exists() and not overwrite:
            continue

        if dest_dir.exists():
            shutil.rmtree(dest_dir)

        shutil.copytree(task_dir, dest_dir)
        copied.append(task_name)

    return copied


def global_tasks_exist() -> bool:
    """Check if any tasks exist in the global tasks directory."""
    global_path = get_global_tasks_path()
    if not global_path.exists():
        return False
    return bool(discover_task_dirs(global_path))
