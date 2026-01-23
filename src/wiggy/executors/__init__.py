"""Executor registry and utilities."""

from wiggy.executors.base import Executor
from wiggy.executors.docker import DockerExecutor
from wiggy.executors.shell import ShellExecutor

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
) -> Executor:
    """Get an executor instance by name. Defaults to docker.

    Args:
        name: Executor name ("docker" or "shell"). Defaults to docker.
        image: Docker image override (only for docker executor).
        model: Model override passed to the executor.
        executor_id: ID for this executor instance (1-indexed).
        quiet: Suppress console output when True.
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
        )

    return ShellExecutor(model_override=model, executor_id=executor_id, quiet=quiet)


def get_executors(
    name: str | None = None,
    count: int = 1,
    image: str | None = None,
    model: str | None = None,
    quiet: bool = False,
) -> list[Executor]:
    """Get multiple executor instances of the same type for parallel execution.

    Args:
        name: Executor name ("docker" or "shell"). Defaults to docker.
        count: Number of executor instances to create.
        image: Docker image override (only for docker executor).
        model: Model override passed to each executor.
        quiet: Suppress console output when True.

    Returns:
        List of executor instances with sequential executor_ids (1, 2, 3...).
    """
    return [
        get_executor(name, image=image, model=model, executor_id=i, quiet=quiet)
        for i in range(1, count + 1)
    ]


__all__ = [
    "DEFAULT_EXECUTOR",
    "EXECUTORS",
    "Executor",
    "get_executor",
    "get_executors",
]
