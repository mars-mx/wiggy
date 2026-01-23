"""Executor registry and utilities."""

from wiggy.executors.base import Executor
from wiggy.executors.docker import DockerExecutor
from wiggy.executors.shell import ShellExecutor

EXECUTORS: dict[str, type[Executor]] = {
    "docker": DockerExecutor,
    "shell": ShellExecutor,
}

DEFAULT_EXECUTOR = "docker"


def get_executor(name: str | None = None, image: str | None = None) -> Executor:
    """Get an executor instance by name. Defaults to docker.

    Args:
        name: Executor name ("docker" or "shell"). Defaults to docker.
        image: Docker image override (only for docker executor).
    """
    executor_name = name or DEFAULT_EXECUTOR
    if executor_name not in EXECUTORS:
        raise ValueError(f"Unknown executor: {executor_name}")

    if executor_name == "docker":
        return DockerExecutor(image_override=image)

    return EXECUTORS[executor_name]()


def get_executors(
    name: str | None = None, count: int = 1, image: str | None = None
) -> list[Executor]:
    """Get multiple executor instances of the same type for parallel execution."""
    return [get_executor(name, image=image) for _ in range(count)]


__all__ = [
    "DEFAULT_EXECUTOR",
    "EXECUTORS",
    "Executor",
    "get_executor",
    "get_executors",
]
