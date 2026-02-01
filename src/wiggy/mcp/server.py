"""Wiggy MCP server with streamable HTTP transport."""

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.lowlevel.server import request_ctx
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ContentBlock, TextContent
from mcp.types import Tool as MCPTool
from starlette.applications import Starlette
from starlette.routing import Mount

from wiggy.history.repository import TaskHistoryRepository
from wiggy.mcp.tools import (
    ORCHESTRATOR_TOOL_NAMES,
    handle_get_commit_log,
    handle_get_git_diff,
    handle_get_knowledge,
    handle_get_process_state,
    handle_inject_steps,
    handle_list_artifact_templates,
    handle_list_artifacts,
    handle_load_artifact,
    handle_load_artifact_template,
    handle_load_result,
    handle_read_result_summary,
    handle_search_knowledge,
    handle_set_process_decision,
    handle_view_knowledge_history,
    handle_write_artifact,
    handle_write_knowledge,
    handle_write_result,
)

logger = logging.getLogger(__name__)


def _is_orchestrator_request(repo: TaskHistoryRepository) -> bool:
    """Check whether the current MCP request originates from an orchestrator task.

    Reads ``x-wiggy-task-id`` from the HTTP request headers via the MCP
    ``request_ctx`` context-var, looks up the corresponding ``TaskLog``,
    and returns its ``is_orchestrator`` flag.  Returns ``False`` when the
    header is missing or the task cannot be found.
    """
    try:
        ctx = request_ctx.get()
    except LookupError:
        return False

    req = getattr(ctx, "request", None)
    if req is None:
        return False

    task_id = getattr(req, "headers", {}).get("x-wiggy-task-id")
    if not task_id:
        return False

    task_log = repo.get_by_task_id(task_id)
    if task_log is None:
        return False

    return task_log.is_orchestrator


class ScopedFastMCP(FastMCP):
    """FastMCP subclass that filters tools based on caller scope.

    Orchestrator-only tools (listed in ``ORCHESTRATOR_TOOL_NAMES``) are
    hidden from ``list_tools`` and guarded in ``call_tool`` when the
    caller is not an orchestrator task.
    """

    def __init__(
        self,
        *args: Any,
        repo: TaskHistoryRepository,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._repo = repo

    async def list_tools(self) -> list[MCPTool]:
        """List tools, excluding orchestrator-only tools for regular tasks."""
        tools = await super().list_tools()
        if _is_orchestrator_request(self._repo):
            return tools
        return [t for t in tools if t.name not in ORCHESTRATOR_TOOL_NAMES]

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        """Call a tool, blocking orchestrator-only tools for regular tasks."""
        if name in ORCHESTRATOR_TOOL_NAMES and not _is_orchestrator_request(self._repo):
            return [
                TextContent(
                    type="text",
                    text=(
                        f"Error: tool '{name}' is only available "
                        "to orchestrator tasks."
                    ),
                )
            ]
        return await super().call_tool(name, arguments)


def _build_mcp_app(
    repo: TaskHistoryRepository, process_id: str, host: str = "127.0.0.1"
) -> FastMCP:
    """Build the FastMCP application with tool registrations.

    Args:
        repo: The task history repository.
        process_id: The current process ID.
        host: The bind host address, used to configure allowed Host headers.

    Returns:
        A configured FastMCP instance.
    """
    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", "host.docker.internal:*"]
    if host not in ("127.0.0.1", "localhost", "::1"):
        allowed_hosts.append(f"{host}:*")

    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=[f"http://{h}" for h in allowed_hosts],
    )

    mcp = ScopedFastMCP(
        "wiggy",
        repo=repo,
        stateless_http=True,
        transport_security=transport_security,
    )

    @mcp.tool()
    async def write_result(
        ctx: Context[Any, Any, Any],
        result: str,
        key_files: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Write a task result.

        Stores the full result text and optionally compresses it into a
        summary. Include findings, decisions made, code changes, file paths,
        and any relevant context that a subsequent task should know about.
        Be thorough - compression happens automatically.

        Args:
            ctx: MCP context (provides access to request headers).
            result: The full result text.
            key_files: List of file paths most relevant to this result
                       (relative to /workspace).
            tags: Optional tags for categorization (e.g. 'bug-fix',
                  'refactor', 'analysis').
        """
        task_id = _extract_task_id(ctx)
        return handle_write_result(repo, task_id, result, key_files or [], tags or [])

    @mcp.tool()
    async def load_result(
        ctx: Context[Any, Any, Any],
        task_name: str | None = None,
        task_id: str | None = None,
    ) -> str:
        """Load a full task result.

        Returns the complete result text, key files, tags, and timestamp.
        Use task_name to load the most recent result for a named task in
        the current process, or task_id for a specific result.

        Args:
            ctx: MCP context.
            task_name: Name of the task whose result to load (e.g.
                       'analyse'). Loads the most recent from the current
                       process.
            task_id: Specific task ID to load (overrides task_name lookup).
        """
        return handle_load_result(repo, process_id, task_name, task_id)

    @mcp.tool()
    async def read_result_summary(
        ctx: Context[Any, Any, Any],
        task_name: str | None = None,
        task_id: str | None = None,
    ) -> str:
        """Read a compressed summary of a task result.

        Returns the Haiku-compressed summary, key files, and timestamp.
        Prefer this over load_result to keep context concise.

        Args:
            ctx: MCP context.
            task_name: Name of the task whose summary to read.
            task_id: Specific task ID (overrides task_name lookup).
        """
        return handle_read_result_summary(repo, process_id, task_name, task_id)

    @mcp.tool()
    async def write_artifact(
        ctx: Context[Any, Any, Any],
        title: str,
        content: str,
        format: str,
        template_name: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Write an artifact document.

        Stores a structured document (PRD, documentation, ADR, etc.)
        associated with the current task. Use list_artifact_templates
        to see available templates, or write freeform content.

        Args:
            ctx: MCP context (provides access to request headers).
            title: The artifact title.
            content: The full artifact content.
            format: Content format: 'json', 'markdown', 'xml', or 'text'.
            template_name: Optional name of the template used to create
                           this artifact (informational).
            tags: Optional tags for categorization.
        """
        task_id = _extract_task_id(ctx)
        return handle_write_artifact(
            repo, task_id, title, content, format, template_name, tags
        )

    @mcp.tool()
    async def load_artifact(
        ctx: Context[Any, Any, Any],
        artifact_id: str,
    ) -> str:
        """Load a full artifact by ID.

        Returns the complete artifact including content, format, tags,
        and metadata.

        Args:
            ctx: MCP context.
            artifact_id: The artifact ID to load.
        """
        return handle_load_artifact(repo, artifact_id)

    @mcp.tool()
    async def list_artifacts(
        ctx: Context[Any, Any, Any],
        task_id: str | None = None,
    ) -> str:
        """List artifacts for a task or the whole process.

        Returns artifact metadata (without content) for browsing.
        Use load_artifact to fetch the full content of a specific artifact.

        Args:
            ctx: MCP context.
            task_id: Optional task ID to filter by. If not provided,
                     lists all artifacts in the current process.
        """
        return handle_list_artifacts(repo, process_id, task_id)

    @mcp.tool()
    async def list_artifact_templates(
        ctx: Context[Any, Any, Any],
    ) -> str:
        """List available artifact templates.

        Returns template names, descriptions, and formats. Use
        load_artifact_template to get the full template content.

        Args:
            ctx: MCP context.
        """
        return handle_list_artifact_templates()

    @mcp.tool()
    async def load_artifact_template(
        ctx: Context[Any, Any, Any],
        template_name: str,
    ) -> str:
        """Load a full artifact template by name.

        Returns the template content, format, and metadata. Use this
        as a starting point when creating artifacts with write_artifact.

        Args:
            ctx: MCP context.
            template_name: Name of the template to load.
        """
        return handle_load_artifact_template(template_name)

    @mcp.tool()
    async def write_knowledge(
        ctx: Context[Any, Any, Any],
        key: str,
        content: str,
        reason: str,
    ) -> str:
        """Write a new version of a knowledge entry.

        Stores persistent knowledge that spans across tasks and processes.
        Each write creates a new version under the given key, preserving
        history. Use descriptive keys like 'api-design-decisions' or
        'deployment-checklist'.

        Args:
            ctx: MCP context.
            key: The knowledge key (e.g. 'api-design-decisions').
            content: The knowledge content to store.
            reason: Why this version was created (e.g. 'added auth section').
        """
        return handle_write_knowledge(repo, key, content, reason)

    @mcp.tool()
    async def get_knowledge(
        ctx: Context[Any, Any, Any],
        key: str,
        version: int | None = None,
    ) -> str:
        """Get a knowledge entry by key.

        Returns the content, version, reason, and timestamp. By default
        returns the latest version. Specify a version number to retrieve
        an older revision.

        Args:
            ctx: MCP context.
            key: The knowledge key to look up.
            version: Optional version number. Defaults to latest.
        """
        return handle_get_knowledge(repo, key, version)

    @mcp.tool()
    async def view_knowledge_history(
        ctx: Context[Any, Any, Any],
        key: str,
    ) -> str:
        """View all versions of a knowledge entry.

        Returns a list of versions with their reasons, timestamps, and
        content previews. Use get_knowledge with a specific version
        number to retrieve the full content of an older revision.

        Args:
            ctx: MCP context.
            key: The knowledge key to look up.
        """
        return handle_view_knowledge_history(repo, key)

    @mcp.tool()
    async def search_knowledge(
        ctx: Context[Any, Any, Any],
        query: str,
        page: int = 1,
    ) -> str:
        """Search knowledge, results, and artifacts by semantic similarity.

        Returns ranked results across all stored content. Each result
        includes a snippet preview and distance score (lower = more
        relevant). Results are paginated with 10 items per page.

        Args:
            ctx: MCP context.
            query: The search query text.
            page: Page number (1-based). Defaults to 1.
        """
        return handle_search_knowledge(repo, query, page)

    @mcp.tool()
    async def get_process_state(
        ctx: Context[Any, Any, Any],
    ) -> str:
        """Get the full current process state.

        Returns completed steps with their results, pending steps,
        current step index, and all orchestrator decisions made so far.
        No arguments needed — the process is identified automatically.

        Args:
            ctx: MCP context.
        """
        return handle_get_process_state(repo, process_id)

    @mcp.tool()
    async def set_process_decision(
        ctx: Context[Any, Any, Any],
        decision: str,
        reasoning: str,
        injected_steps: list[dict[str, str]] | None = None,
    ) -> str:
        """Record the orchestrator's decision for the current phase.

        Use this to record whether the process should proceed, inject
        new steps, or abort. The decision is persisted and visible to
        subsequent orchestrator invocations.

        Args:
            ctx: MCP context (provides access to request headers).
            decision: One of 'proceed', 'inject', or 'abort'.
            reasoning: Explanation of why this decision was made.
            injected_steps: Required when decision is 'inject'. List of
                objects with 'task_name' and 'prompt' keys describing
                the steps to inject.
        """
        task_id = _extract_task_id(ctx)
        return handle_set_process_decision(
            repo, process_id, task_id, decision, reasoning, injected_steps
        )

    @mcp.tool()
    async def inject_steps(
        ctx: Context[Any, Any, Any],
        steps: list[dict[str, str]],
    ) -> str:
        """Inject new steps into the running process.

        Adds steps before the current step. Each step must reference a
        valid task name. The orchestrator loop will execute injected steps
        before continuing with the original step.

        Args:
            ctx: MCP context (provides access to request headers).
            steps: List of objects with 'task_name' (required) and
                'prompt' (optional) keys describing the steps to inject.
        """
        task_id = _extract_task_id(ctx)
        return handle_inject_steps(repo, task_id, process_id, steps)

    @mcp.tool()
    async def get_git_diff(
        ctx: Context[Any, Any, Any],
        since_commit: str | None = None,
    ) -> str:
        """Get the git diff for the process worktree.

        Returns the unified diff of all changes since the given commit
        (or since the first commit of the process if not specified).
        Output is truncated at 50KB with a note if it exceeds that limit.

        Args:
            ctx: MCP context (provides access to request headers).
            since_commit: Optional commit hash to diff from. Defaults to
                the earliest commit recorded for this process.
        """
        task_id = _extract_task_id(ctx)
        return handle_get_git_diff(repo, task_id, process_id, since_commit)

    @mcp.tool()
    async def get_commit_log(
        ctx: Context[Any, Any, Any],
        since_commit: str | None = None,
    ) -> str:
        """Get commit messages since the process started.

        Returns a list of commits (hash and message) made in the process
        worktree since the given commit or the first commit of the process.

        Args:
            ctx: MCP context (provides access to request headers).
            since_commit: Optional commit hash to log from. Defaults to
                the earliest commit recorded for this process.
        """
        task_id = _extract_task_id(ctx)
        return handle_get_commit_log(repo, task_id, process_id, since_commit)

    return mcp


def _extract_task_id(ctx: Context[Any, Any, Any]) -> str | None:
    """Extract the X-Wiggy-Task-ID header from the MCP context.

    Args:
        ctx: The MCP tool context.

    Returns:
        The task ID string or None if not present.
    """
    try:
        req = ctx.request_context.request
        task_id = req.headers.get("x-wiggy-task-id") if req else None
        if task_id is None:
            logger.debug(
                "No X-Wiggy-Task-ID header found (request=%s)",
                type(req).__name__ if req else "None",
            )
        return task_id
    except (AttributeError, TypeError):
        logger.debug("Failed to extract task_id from MCP context", exc_info=True)
        return None


class WiggyMCPServer:
    """Manages the MCP server lifecycle.

    Runs a FastMCP server on a dynamically assigned port using
    streamable HTTP transport in a background thread.
    """

    def __init__(
        self,
        repo: TaskHistoryRepository,
        process_id: str,
        host: str = "127.0.0.1",
    ) -> None:
        self.repo = repo
        self.process_id = process_id
        self.host = host
        self.port: int | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        """Start the MCP server on a free port.

        Returns the port number. Binds to ``self.host``.
        """
        mcp_app = _build_mcp_app(self.repo, self.process_id, self.host)
        http_app = mcp_app.streamable_http_app()
        session_mgr = mcp_app.session_manager

        @asynccontextmanager
        async def _lifespan(app: Starlette) -> AsyncIterator[None]:
            async with session_mgr.run():
                yield

        starlette_app = Starlette(
            routes=[Mount("/", app=http_app)],
            lifespan=_lifespan,
        )

        config = uvicorn.Config(
            app=starlette_app,
            host=self.host,
            port=0,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)

        self._thread = threading.Thread(
            target=asyncio.run,
            args=(self._server.serve(),),
            daemon=True,
        )
        self._thread.start()

        # Wait for the server to bind and read the actual port
        self.port = self._wait_for_port()
        logger.info("MCP server started on %s:%d", self.host, self.port)
        return self.port

    def _wait_for_port(self, timeout: float = 10.0) -> int:
        """Wait for the uvicorn server to bind and return the port.

        Args:
            timeout: Maximum seconds to wait for the server to start.

        Returns:
            The port number the server is listening on.

        Raises:
            RuntimeError: If the server fails to start within the timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._server and self._server.started:
                servers: Any = getattr(self._server, "servers", [])
                for srv in servers:
                    sockets = getattr(srv, "sockets", None)
                    if sockets:
                        addr: Any = sockets[0].getsockname()
                        return int(addr[1])
            time.sleep(0.05)
        raise RuntimeError("MCP server failed to start within timeout")

    def stop(self) -> None:
        """Stop the MCP server gracefully."""
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._server = None
        self.port = None
        logger.info("MCP server stopped")
