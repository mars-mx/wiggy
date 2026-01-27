"""Task definitions and discovery."""

from wiggy.tasks.base import TaskSpec
from wiggy.tasks.loader import (
    copy_default_tasks_to_user,
    get_all_tasks,
    get_available_task_names,
    get_global_tasks_path,
    get_local_tasks_path,
    get_package_tasks_path,
    get_task_by_name,
    get_task_search_paths,
    global_tasks_exist,
)

__all__ = [
    "TaskSpec",
    "copy_default_tasks_to_user",
    "get_all_tasks",
    "get_available_task_names",
    "get_global_tasks_path",
    "get_local_tasks_path",
    "get_package_tasks_path",
    "get_task_by_name",
    "get_task_search_paths",
    "global_tasks_exist",
]

# Default task names for reference
DEFAULT_TASKS: tuple[str, ...] = (
    "analyse",
    "create-task",
    "implement",
    "research",
    "review",
    "test",
)
