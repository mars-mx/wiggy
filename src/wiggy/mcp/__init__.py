"""MCP integrations for Wiggy."""

from wiggy.mcp.compression import CompressionError
from wiggy.mcp.networking import resolve_mcp_bind_host
from wiggy.mcp.server import WiggyMCPServer

# MCP tool names as Claude Code identifies them (mcp__<server>__<tool>).
# The server name "wiggy" comes from FastMCP("wiggy", ...) in server.py.
# Update this tuple if tools are added/renamed in server.py.
MCP_TOOL_NAMES: tuple[str, ...] = (
    "mcp__wiggy__write_result",
    "mcp__wiggy__load_result",
    "mcp__wiggy__read_result_summary",
)

__all__ = [
    "MCP_TOOL_NAMES",
    "WiggyMCPServer",
    "CompressionError",
    "resolve_mcp_bind_host",
]
