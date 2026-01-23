"""Docker executor implementation."""

from collections.abc import Iterator

from wiggy.engines.base import Engine
from wiggy.executors.base import Executor


class DockerExecutor(Executor):
    """Executor that runs engines in Docker containers."""

    name = "docker"

    def __init__(self) -> None:
        self._exit_code: int | None = None

    def setup(self, engine: Engine) -> None:
        """Set up the Docker container for the given engine."""
        pass  # TODO: Docker container setup

    def run(self) -> Iterator[str]:
        """Run the engine in a Docker container.

        Yields stdout lines as they are produced.
        """
        # TODO: Run engine in container, yield stdout lines
        yield from []
        self._exit_code = 0

    def teardown(self) -> None:
        """Clean up the Docker container."""
        pass  # TODO: Container cleanup

    @property
    def exit_code(self) -> int | None:
        """Return the exit code after run() completes, or None if still running."""
        return self._exit_code
