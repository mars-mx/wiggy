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
    handle_load_result,
    handle_read_result_summary,
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
