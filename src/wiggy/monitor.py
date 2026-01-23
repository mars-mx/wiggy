"""Real-time monitor for executor output using Rich."""

from threading import Lock

from rich.live import Live
from rich.table import Table

from wiggy.console import console
from wiggy.parsers.messages import MessageType, ParsedMessage


class Monitor:
    """Real-time status display for executors using Rich Live."""

    def __init__(
        self, engine_name: str, executor_count: int = 1, model: str | None = None
    ) -> None:
        """Initialize the monitor.

        Args:
            engine_name: Name of the engine being run.
            executor_count: Number of executors to track.
            model: Optional model name to display.
        """
        self._engine_name = engine_name
        self._executor_count = executor_count
        self._model = model
        self._statuses: dict[int, str] = {}
        self._lock = Lock()
        self._live = Live(console=console, auto_refresh=False)

    def start(self) -> None:
        """Start the live display."""
        self._live.start()

    def update(self, executor_id: int, message: ParsedMessage) -> None:
        """Update status for an executor.

        Args:
            executor_id: ID of the executor (1-indexed).
            message: The parsed message to display.
        """
        # Skip empty content and non-structured message types
        # RAW messages are terminal noise (ANSI escapes, etc.) when using stream-json
        if (
            not message.content
            or message.message_type == MessageType.STREAM_EVENT
            or message.message_type == MessageType.RAW
        ):
            return

        # Truncate long messages
        content = message.content
        if len(content) > 60:
            content = content[:57] + "..."

        # Replace newlines with spaces for single-line display
        content = content.replace("\n", " ")

        with self._lock:
            self._statuses[executor_id] = content
            self._refresh()

    def _refresh(self) -> None:
        """Refresh the live display."""
        table = Table(show_header=False, box=None, padding=(0, 1))

        # Build engine label with optional model
        if self._model:
            engine_label = f"{self._engine_name} ({self._model})"
        else:
            engine_label = self._engine_name

        for exec_id in sorted(self._statuses.keys()):
            status = self._statuses[exec_id]
            table.add_row(
                f"[cyan][{engine_label}][/cyan]",
                f"Executor ({exec_id}):",
                f"[dim]{status}[/dim]",
            )

        self._live.update(table)
        self._live.refresh()

    def stop(self) -> None:
        """Stop the live display."""
        self._live.stop()
