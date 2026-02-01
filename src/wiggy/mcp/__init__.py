"""MCP integrations for Wiggy."""

from wiggy.mcp.compression import CompressionError
from wiggy.mcp.networking import resolve_mcp_bind_host
from wiggy.mcp.server import WiggyMCPServer
from wiggy.mcp.tools import ORCHESTRATOR_TOOL_NAMES

# MCP tool names as Claude Code identifies them (mcp__<server>__<tool>).
# The server name "wiggy" comes from FastMCP("wiggy", ...) in server.py.
# Update this tuple if tools are added/renamed in server.py.
MCP_TOOL_NAMES: tuple[str, ...] = (
    "mcp__wiggy__write_result",
    "mcp__wiggy__load_result",
    "mcp__wiggy__read_result_summary",
    "mcp__wiggy__write_artifact",
    "mcp__wiggy__load_artifact",
    "mcp__wiggy__list_artifacts",
    "mcp__wiggy__list_artifact_templates",
    "mcp__wiggy__load_artifact_template",
    "mcp__wiggy__write_knowledge",
    "mcp__wiggy__get_knowledge",
    "mcp__wiggy__view_knowledge_history",
    "mcp__wiggy__search_knowledge",
    "mcp__wiggy__get_process_state",
    "mcp__wiggy__set_process_decision",
    "mcp__wiggy__inject_steps",
    "mcp__wiggy__get_git_diff",
    "mcp__wiggy__get_commit_log",
)

__all__ = [
    "MCP_TOOL_NAMES",
    "ORCHESTRATOR_TOOL_NAMES",
    "WiggyMCPServer",
    "CompressionError",
    "resolve_mcp_bind_host",
]
