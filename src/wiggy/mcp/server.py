"""Wiggy MCP server with streamable HTTP transport."""

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Mount

from wiggy.history.repository import TaskHistoryRepository
from wiggy.mcp.tools import (
    handle_get_knowledge,
    handle_list_artifact_templates,
    handle_list_artifacts,
    handle_load_artifact,
    handle_load_artifact_template,
    handle_load_result,
    handle_read_result_summary,
    handle_search_knowledge,
    handle_view_knowledge_history,
    handle_write_artifact,
    handle_write_knowledge,
    handle_write_result,
)

logger = logging.getLogger(__name__)


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

    mcp = FastMCP("wiggy", stateless_http=True, transport_security=transport_security)

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
