"""Shell executor implementation."""

from collections.abc import Iterator

from wiggy.engines.base import Engine
from wiggy.executors.base import Executor
from wiggy.parsers.messages import ParsedMessage, SessionSummary


class ShellExecutor(Executor):
    """Executor that runs engines directly in the current shell."""

    name = "shell"

    def __init__(
        self,
        model_override: str | None = None,
        executor_id: int = 1,
        quiet: bool = False,
    ) -> None:
        self._model_override = model_override
        self.executor_id = executor_id
        self.quiet = quiet
        self._exit_code: int | None = None

    def setup(self, engine: Engine, prompt: str | None = None) -> None:
        """Set up the shell environment for the given engine."""
        pass  # TODO: Shell environment setup

    def run(self) -> Iterator[ParsedMessage]:
        """Run the engine in the current shell.

        Yields ParsedMessage objects as they are produced.
        """
        # TODO: Run engine in shell, yield parsed messages
        yield from []
        self._exit_code = 0

    def teardown(self) -> None:
        """Clean up the shell environment."""
        pass  # TODO: Shell cleanup

    @property
    def exit_code(self) -> int | None:
        """Return the exit code after run() completes, or None if still running."""
        return self._exit_code

    @property
    def summary(self) -> SessionSummary | None:
        """Return the session summary after run() completes, or None if unavailable."""
        return None  # TODO: Implement when shell execution is implemented
