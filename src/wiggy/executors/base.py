"""Base executor class."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import TextIO

from wiggy.engines.base import Engine
from wiggy.parsers.messages import ParsedMessage


class Executor(ABC):
    """Base class for execution environments."""

    name: str
    executor_id: int = 1
    quiet: bool = False
    _log_file: TextIO | None = None
    _session_id: str | None = None

    def _generate_session_id(self) -> str:
        """Generate a session ID with format: YYYYMMDD_HHMMSS_exec{N}."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{timestamp}_exec{self.executor_id}"

    def _open_log(self) -> None:
        """Open the log file for this session."""
        if self._session_id is None:
            self._session_id = self._generate_session_id()
        log_path = Path.cwd() / ".wiggy" / "logs" / f"{self._session_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = open(log_path, "w", encoding="utf-8")

    def _write_log(self, line: str) -> None:
        """Write a line to the log file."""
        if self._log_file is not None:
            self._log_file.write(line + "\n")
            self._log_file.flush()

    def _close_log(self) -> None:
        """Close the log file."""
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    @abstractmethod
    def setup(self, engine: Engine, prompt: str | None = None) -> None:
        """Set up the execution environment for the given engine."""
        ...

    @abstractmethod
    def run(self) -> Iterator[ParsedMessage]:
        """Run the engine in the execution environment.

        Yields ParsedMessage objects as they are produced.
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
