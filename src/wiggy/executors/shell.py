"""Shell executor implementation."""

from collections.abc import Iterator

from wiggy.engines.base import Engine
from wiggy.executors.base import Executor


class ShellExecutor(Executor):
    """Executor that runs engines directly in the current shell."""

    name = "shell"

    def __init__(self) -> None:
        self._exit_code: int | None = None

    def setup(self, engine: Engine, prompt: str | None = None) -> None:
        """Set up the shell environment for the given engine."""
        pass  # TODO: Shell environment setup

    def run(self) -> Iterator[str]:
        """Run the engine in the current shell.

        Yields stdout lines as they are produced.
        """
        # TODO: Run engine in shell, yield stdout lines
        yield from []
        self._exit_code = 0

    def teardown(self) -> None:
        """Clean up the shell environment."""
        pass  # TODO: Shell cleanup

    @property
    def exit_code(self) -> int | None:
        """Return the exit code after run() completes, or None if still running."""
        return self._exit_code
