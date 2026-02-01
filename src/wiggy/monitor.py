"""Real-time monitoring dashboard using Rich Live."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from wiggy.console import console
from wiggy.parsers.messages import MessageType, ParsedMessage


@dataclass
class StepInfo:
    """Tracks a process step for display in the header."""

    name: str
    status: str = "pending"  # pending, running, done, failed


@dataclass
class WorkerState:
    """Tracks the current state of a single executor/worker."""

    executor_id: int
    engine: str
    model: str | None = None
    task_name: str | None = None
    step_label: str | None = None
    last_action: str = "Waiting..."
    status: str = "idle"  # idle, running, done, failed


def _parse_action(message: ParsedMessage) -> str | None:
    """Extract a concise action description from a parsed message.

    For ASSISTANT messages, looks at content blocks for tool_use to
    produce labels like "Read: src/foo.py" or "Bash: npm test".
    Falls back to truncated text content.
    """
    if message.message_type == MessageType.ASSISTANT:
        # Try to find tool_use blocks in metadata
        msg_data = message.metadata.get("message", {})
        content_blocks: list[dict[str, Any]] = msg_data.get("content", [])

        # Find the last tool_use block (most recent action)
        tool_blocks = [b for b in content_blocks if b.get("type") == "tool_use"]
        if tool_blocks:
            block = tool_blocks[-1]
            tool_name = block.get("name", "")
            tool_input = block.get("input", {})
            return _format_tool_action(tool_name, tool_input)

    # Fall back to text content
    if not message.content:
        return None

    content = message.content.replace("\n", " ").strip()
    if len(content) > 80:
        content = content[:77] + "..."
    return content


def _format_tool_action(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Format a tool call into a short action string."""
    if tool_name == "Read":
        path = tool_input.get("file_path", "")
        return f"Read: {_short_path(path)}"
    if tool_name == "Write":
        path = tool_input.get("file_path", "")
        return f"Write: {_short_path(path)}"
    if tool_name == "Edit":
        path = tool_input.get("file_path", "")
        return f"Edit: {_short_path(path)}"
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if len(cmd) > 60:
            cmd = cmd[:57] + "..."
        return f"Bash: {cmd}"
    if tool_name == "Glob":
        pattern = tool_input.get("pattern", "")
        return f"Glob: {pattern}"
    if tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        return f"Grep: {pattern}"
    if tool_name == "WebFetch":
        url = tool_input.get("url", "")
        if len(url) > 50:
            url = url[:47] + "..."
        return f"WebFetch: {url}"
    if tool_name == "Task":
        desc = tool_input.get("description", "")
        return f"Task: {desc}"
    if tool_name == "TodoWrite":
        return "TodoWrite"
    # Generic fallback for any tool
    return tool_name


def _short_path(path: str) -> str:
    """Shorten a file path for display."""
    if not path:
        return ""
    # Show last 2 path components at most
    parts = path.replace("\\", "/").split("/")
    if len(parts) <= 3:
        return path
    return ".../" + "/".join(parts[-2:])


class Monitor:
    """Real-time dashboard for executor output using Rich Live.

    Displays a top status bar with process/MCP info and step progress,
    followed by a table of worker statuses showing task, step, and
    current action parsed from engine JSON output.
    """

    def __init__(
        self,
        engine_name: str,
        executor_count: int = 1,
        model: str | None = None,
        *,
        process_name: str | None = None,
        mcp_host: str | None = None,
        mcp_port: int | None = None,
        step_names: list[str] | None = None,
    ) -> None:
        self._engine_name = engine_name
        self._executor_count = executor_count
        self._model = model
        self._process_name = process_name
        self._mcp_host = mcp_host
        self._mcp_port = mcp_port
        self._lock = Lock()
        self._live = Live(
            console=console,
            auto_refresh=False,
            redirect_stderr=False,
            redirect_stdout=False,
        )
        self._start_time: float | None = None
        self._saved_log_level: int | None = None

        # Step tracking for header progress display
        self._steps: list[StepInfo] = []
        if step_names:
            self._steps = [StepInfo(name=n) for n in step_names]

        # Worker state keyed by executor_id
        self._workers: dict[int, WorkerState] = {}
        for i in range(1, executor_count + 1):
            self._workers[i] = WorkerState(
                executor_id=i,
                engine=engine_name,
                model=model,
            )

    # -- Public API -----------------------------------------------------------

    def start(self) -> None:
        """Start the live display and suppress logging to console."""
        self._start_time = time.monotonic()
        # Suppress logging while live display is active
        # Using logging.disable() preserves non-console handlers
        self._saved_log_level = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        self._live.start()
        self._refresh()

    def stop(self) -> None:
        """Stop the live display and restore logging."""
        self._live.stop()
        # Restore logging
        if self._saved_log_level is not None:
            logging.disable(self._saved_log_level)
            self._saved_log_level = None

    def set_step(
        self,
        executor_id: int,
        *,
        task_name: str | None = None,
        step_label: str | None = None,
        step_index: int | None = None,
    ) -> None:
        """Update the task/step for a worker.

        Also updates the step tracking in the header when step_index
        is provided and matches a known step.

        Args:
            executor_id: 1-indexed executor ID.
            task_name: Current task name (e.g. "analyse").
            step_label: Step label (e.g. "Step 2/4").
            step_index: 0-indexed step number for tracking progress.
        """
        with self._lock:
            worker = self._workers.get(executor_id)
            if worker is None:
                return
            if task_name is not None:
                worker.task_name = task_name
            if step_label is not None:
                worker.step_label = step_label
            # Update step tracking by index if provided
            if step_index is not None and 0 <= step_index < len(self._steps):
                step = self._steps[step_index]
                if step.status == "pending":
                    step.status = "running"
            worker.status = "running"
            worker.last_action = "Starting..."
            self._refresh()

    def set_worker_done(
        self, executor_id: int, *, success: bool = True, step_index: int | None = None
    ) -> None:
        """Mark a worker as completed.

        Args:
            executor_id: 1-indexed executor ID.
            success: Whether the worker succeeded.
            step_index: 0-indexed step number for tracking progress.
        """
        with self._lock:
            worker = self._workers.get(executor_id)
            if worker is None:
                return
            worker.status = "done" if success else "failed"
            worker.last_action = "Done" if success else "Failed"
            # Update step tracking by index if provided
            if step_index is not None and 0 <= step_index < len(self._steps):
                step = self._steps[step_index]
                if step.status == "running":
                    step.status = "done" if success else "failed"
            self._refresh()

    def update(self, executor_id: int, message: ParsedMessage) -> None:
        """Update status for an executor from a parsed message.

        Parses tool calls from message metadata when available to show
        meaningful action descriptions (e.g. "Read: src/foo.py").

        Args:
            executor_id: ID of the executor (1-indexed).
            message: The parsed message to display.
        """
        # Skip non-displayable message types
        if message.message_type in (MessageType.STREAM_EVENT, MessageType.RAW):
            return

        action = _parse_action(message)
        if not action:
            return

        with self._lock:
            worker = self._workers.get(executor_id)
            if worker is None:
                return
            worker.last_action = action
            worker.status = "running"
            self._refresh()

    def update_mcp(
        self, *, host: str | None = None, port: int | None = None
    ) -> None:
        """Update MCP connection info."""
        with self._lock:
            if host is not None:
                self._mcp_host = host
            if port is not None:
                self._mcp_port = port
            self._refresh()

    def update_steps(self, step_names: list[str]) -> None:
        """Update the step list (e.g. after dynamic step injection)."""
        with self._lock:
            # Preserve status of existing steps by index to handle duplicate names
            existing_statuses = [s.status for s in self._steps]
            self._steps = [
                StepInfo(
                    name=name,
                    status=(
                        existing_statuses[i]
                        if i < len(existing_statuses)
                        else "pending"
                    ),
                )
                for i, name in enumerate(step_names)
            ]
            self._refresh()

    # -- Rendering ------------------------------------------------------------

    def _elapsed(self) -> str:
        """Return formatted elapsed time."""
        if self._start_time is None:
            return "0s"
        elapsed = time.monotonic() - self._start_time
        minutes = int(elapsed) // 60
        seconds = int(elapsed) % 60
        if minutes > 0:
            return f"{minutes}m {seconds:02d}s"
        return f"{seconds}s"

    def _build_status_bar(self) -> Text:
        """Build the top status bar."""
        parts = Text()

        # Process name
        if self._process_name:
            parts.append(" Process: ", style="dim")
            parts.append(self._process_name, style="bold cyan")
            parts.append("  ", style="dim")

        # Engine
        engine_label = self._engine_name
        if self._model:
            engine_label = f"{self._engine_name} ({self._model})"
        parts.append("Engine: ", style="dim")
        parts.append(engine_label, style="cyan")
        parts.append("  ", style="dim")

        # MCP status
        parts.append("MCP: ", style="dim")
        if self._mcp_port:
            mcp_label = f"{self._mcp_host or '127.0.0.1'}:{self._mcp_port}"
            parts.append(mcp_label, style="green")
        else:
            parts.append("off", style="yellow")

        # Elapsed time
        parts.append("  ", style="dim")
        parts.append("Elapsed: ", style="dim")
        parts.append(self._elapsed(), style="bold")

        return parts

    def _build_steps_bar(self) -> Text | None:
        """Build step progress indicators for the header."""
        if not self._steps:
            return None

        parts = Text()
        parts.append(" Steps: ", style="dim")

        for i, step in enumerate(self._steps):
            if i > 0:
                parts.append(" > ", style="dim")

            if step.status == "done":
                parts.append(step.name, style="green")
                parts.append(" \u2713", style="bold green")
            elif step.status == "failed":
                parts.append(step.name, style="red")
                parts.append(" \u2717", style="bold red")
            elif step.status == "running":
                parts.append(step.name, style="bold yellow")
                parts.append(" \u25cf", style="yellow")
            else:
                parts.append(step.name, style="dim")

        return parts

    def _build_workers_table(self) -> Table:
        """Build the workers status table."""
        table = Table(
            show_header=True,
            header_style="bold",
            box=None,
            padding=(0, 2),
            expand=True,
        )
        table.add_column("#", style="dim", width=3, justify="right")
        table.add_column("Task", style="cyan", min_width=14)
        table.add_column("Step", style="dim", min_width=10)
        table.add_column("Status", min_width=8)
        table.add_column("Action", ratio=1)

        for executor_id in sorted(self._workers.keys()):
            worker = self._workers[executor_id]

            # Status indicator
            if worker.status == "running":
                status_text = Text("running", style="green")
            elif worker.status == "done":
                status_text = Text("done", style="bold green")
            elif worker.status == "failed":
                status_text = Text("failed", style="bold red")
            else:
                status_text = Text("idle", style="dim")

            task_name = worker.task_name or "-"
            step_label = worker.step_label or "-"
            action = Text(worker.last_action, style="dim")

            table.add_row(
                str(executor_id),
                task_name,
                step_label,
                status_text,
                action,
            )

        return table

    def _render(self) -> Panel:
        """Build the full dashboard panel."""
        renderables: list[Text | Table] = []

        status_bar = self._build_status_bar()
        renderables.append(status_bar)

        steps_bar = self._build_steps_bar()
        if steps_bar is not None:
            renderables.append(steps_bar)

        renderables.append(Text("\u2500" * 60, style="dim"))
        renderables.append(self._build_workers_table())

        content = Group(*renderables)
        return Panel(content, title="[bold]wiggy[/bold]", border_style="dim")

    def _refresh(self) -> None:
        """Refresh the live display."""
        self._live.update(self._render())
        self._live.refresh()
