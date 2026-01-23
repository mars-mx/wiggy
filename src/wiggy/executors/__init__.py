"""Executor registry and utilities."""

from wiggy.executors.base import Executor
from wiggy.executors.docker import DockerExecutor
from wiggy.executors.shell import ShellExecutor

EXECUTORS: dict[str, type[Executor]] = {
    "docker": DockerExecutor,
    "shell": ShellExecutor,
}

DEFAULT_EXECUTOR = "docker"


def get_executor(name: str | None = None) -> Executor:
    """Get an executor instance by name. Defaults to docker."""
    executor_name = name or DEFAULT_EXECUTOR
    if executor_name not in EXECUTORS:
        raise ValueError(f"Unknown executor: {executor_name}")
    return EXECUTORS[executor_name]()


def get_executors(name: str | None = None, count: int = 1) -> list[Executor]:
    """Get multiple executor instances of the same type for parallel execution."""
    return [get_executor(name) for _ in range(count)]


__all__ = [
    "DEFAULT_EXECUTOR",
    "EXECUTORS",
    "Executor",
    "get_executor",
    "get_executors",
]
