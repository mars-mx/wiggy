"""Base executor class."""

from abc import ABC, abstractmethod
from collections.abc import Iterator

from wiggy.engines.base import Engine


class Executor(ABC):
    """Base class for execution environments."""

    name: str

    @abstractmethod
    def setup(self, engine: Engine, prompt: str | None = None) -> None:
        """Set up the execution environment for the given engine."""
        ...

    @abstractmethod
    def run(self) -> Iterator[str]:
        """Run the engine in the execution environment.

        Yields stdout lines as they are produced.
        """
        ...

    @abstractmethod
    def teardown(self) -> None:
        """Clean up the execution environment."""
        ...

    @property
    @abstractmethod
    def exit_code(self) -> int | None:
        """Return the exit code after run() completes, or None if still running."""
        ...
