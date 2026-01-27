"""Executor registry and utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from wiggy.executors.base import Executor
from wiggy.executors.docker import DockerExecutor
from wiggy.executors.shell import ShellExecutor

if TYPE_CHECKING:
    from wiggy.git import WorktreeInfo

EXECUTORS: dict[str, type[Executor]] = {
    "docker": DockerExecutor,
    "shell": ShellExecutor,
}

DEFAULT_EXECUTOR = "docker"


def get_executor(
    name: str | None = None,
    image: str | None = None,
    model: str | None = None,
    executor_id: int = 1,
    quiet: bool = False,
    worktree_info: WorktreeInfo | None = None,
    extra_args: tuple[str, ...] = (),
    allowed_tools: list[str] | None = None,
    mount_cwd: bool = False,
    global_tasks_rw: bool = False,
) -> Executor:
    """Get an executor instance by name. Defaults to docker.

    Args:
        name: Executor name ("docker" or "shell"). Defaults to docker.
        image: Docker image override (only for docker executor).
        model: Model override passed to the executor.
        executor_id: ID for this executor instance (1-indexed).
        quiet: Suppress console output when True.
        worktree_info: WorktreeInfo for git worktree to mount as /workspace.
        extra_args: Additional CLI arguments to pass to the engine.
        allowed_tools: List of tools to allow (for --allowedTools flag).
        mount_cwd: Mount current working directory as /workspace.
        global_tasks_rw: Mount global tasks directory as read-write.
    """
    executor_name = name or DEFAULT_EXECUTOR
    if executor_name not in EXECUTORS:
        raise ValueError(f"Unknown executor: {executor_name}")

    if executor_name == "docker":
        return DockerExecutor(
            image_override=image,
            model_override=model,
            executor_id=executor_id,
            quiet=quiet,
            worktree_info=worktree_info,
            extra_args=extra_args,
            allowed_tools=allowed_tools,
            mount_cwd=mount_cwd,
            global_tasks_rw=global_tasks_rw,
        )

    return ShellExecutor(model_override=model, executor_id=executor_id, quiet=quiet)


def get_executors(
    name: str | None = None,
    count: int = 1,
    image: str | None = None,
    model: str | None = None,
    quiet: bool = False,
    worktree_infos: list[WorktreeInfo] | None = None,
    extra_args: tuple[str, ...] = (),
    allowed_tools: list[str] | None = None,
    mount_cwd: bool = False,
    global_tasks_rw: bool = False,
) -> list[Executor]:
    """Get multiple executor instances of the same type for parallel execution.

    Args:
        name: Executor name ("docker" or "shell"). Defaults to docker.
        count: Number of executor instances to create.
        image: Docker image override (only for docker executor).
        model: Model override passed to each executor.
        quiet: Suppress console output when True.
        worktree_infos: List of WorktreeInfo objects, one per executor.
            Must match count if provided.
        extra_args: Additional CLI arguments to pass to each engine.
        allowed_tools: List of tools to allow (for --allowedTools flag).
        mount_cwd: Mount current working directory as /workspace.
        global_tasks_rw: Mount global tasks directory as read-write.

    Returns:
        List of executor instances with sequential executor_ids (1, 2, 3...).
    """
    if worktree_infos and len(worktree_infos) != count:
        raise ValueError(
            f"worktree_infos length ({len(worktree_infos)}) must match count ({count})"
        )

    return [
        get_executor(
            name,
            image=image,
            model=model,
            executor_id=i,
            quiet=quiet,
            worktree_info=worktree_infos[i - 1] if worktree_infos else None,
            extra_args=extra_args,
            allowed_tools=allowed_tools,
            mount_cwd=mount_cwd,
            global_tasks_rw=global_tasks_rw,
        )
        for i in range(1, count + 1)
    ]


__all__ = [
    "DEFAULT_EXECUTOR",
    "EXECUTORS",
    "Executor",
    "get_executor",
    "get_executors",
]
