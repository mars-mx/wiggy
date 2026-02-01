"""Tests for MCP tool scoping (shared vs orchestrator-exclusive)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from wiggy.history import TaskHistoryRepository, TaskLog
from wiggy.mcp.server import ScopedFastMCP, _is_orchestrator_request
from wiggy.mcp.tools import ORCHESTRATOR_TOOL_NAMES, TOOL_SCOPES


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "history.db"


@pytest.fixture
def repo(temp_db: Path) -> TaskHistoryRepository:
    return TaskHistoryRepository(db_path=temp_db)


def _make_task(
    task_id: str = "abcd1234",
    process_id: str = "proc5678",
    is_orchestrator: bool = False,
    **kwargs: object,
) -> TaskLog:
    defaults: dict[str, object] = {
        "branch": "wiggy/test",
        "worktree": "/tmp/worktree",
        "main_repo": "/home/user/project",
        "engine": "claude",
        "created_at": datetime.now(UTC).isoformat(),
    }
    defaults.update(kwargs)
    return TaskLog(
        task_id=task_id,
        process_id=process_id,
        executor_id=1,
        is_orchestrator=is_orchestrator,
        **defaults,  # type: ignore[arg-type]
    )


def _set_request_ctx(task_id: str | None) -> Any:
    """Set a fake request_ctx with the given task_id header.

    Returns the token so the caller can reset it.
    """
    from mcp.server.lowlevel.server import request_ctx

    mock_request = MagicMock()
    if task_id is not None:
        mock_request.headers = {"x-wiggy-task-id": task_id}
    else:
        mock_request.headers = {}

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request
    return request_ctx.set(mock_ctx)


def _clear_request_ctx(token: Any) -> None:
    from mcp.server.lowlevel.server import request_ctx

    request_ctx.reset(token)


# ── TOOL_SCOPES sanity ────────────────────────────────────────────────


class TestToolScopes:
    """Verify the TOOL_SCOPES constant is consistent."""

    def test_orchestrator_names_match_scopes(self) -> None:
        expected = frozenset(
            name for name, scope in TOOL_SCOPES.items() if scope == "orchestrator"
        )
        assert ORCHESTRATOR_TOOL_NAMES == expected

    def test_all_scopes_are_valid(self) -> None:
        for name, scope in TOOL_SCOPES.items():
            assert scope in ("shared", "orchestrator"), (
                f"Tool '{name}' has invalid scope '{scope}'"
            )


# ── _is_orchestrator_request tests ────────────────────────────────────


class TestIsOrchestratorRequest:
    """Tests for the _is_orchestrator_request helper."""

    def test_no_request_ctx_returns_false(
        self, repo: TaskHistoryRepository
    ) -> None:
        assert _is_orchestrator_request(repo) is False

    def test_missing_header_returns_false(
        self, repo: TaskHistoryRepository
    ) -> None:
        token = _set_request_ctx(None)
        try:
            assert _is_orchestrator_request(repo) is False
        finally:
            _clear_request_ctx(token)

    def test_unknown_task_id_returns_false(
        self, repo: TaskHistoryRepository
    ) -> None:
        token = _set_request_ctx("nonexistent")
        try:
            assert _is_orchestrator_request(repo) is False
        finally:
            _clear_request_ctx(token)

    def test_regular_task_returns_false(
        self, repo: TaskHistoryRepository
    ) -> None:
        task = _make_task(task_id="reg001", is_orchestrator=False)
        repo.create(task)

        token = _set_request_ctx("reg001")
        try:
            assert _is_orchestrator_request(repo) is False
        finally:
            _clear_request_ctx(token)

    def test_orchestrator_task_returns_true(
        self, repo: TaskHistoryRepository
    ) -> None:
        task = _make_task(task_id="orch01", is_orchestrator=True)
        repo.create(task)

        token = _set_request_ctx("orch01")
        try:
            assert _is_orchestrator_request(repo) is True
        finally:
            _clear_request_ctx(token)


# ── ScopedFastMCP.list_tools tests ────────────────────────────────────


class TestScopedListTools:
    """Tests for ScopedFastMCP.list_tools filtering."""

    @pytest.fixture
    def mcp(self, repo: TaskHistoryRepository) -> ScopedFastMCP:
        """Build a ScopedFastMCP with all tools registered."""
        from wiggy.mcp.server import _build_mcp_app

        return _build_mcp_app(repo, "proc5678")  # type: ignore[return-value]

    @pytest.mark.anyio
    async def test_regular_task_hides_orchestrator_tools(
        self, mcp: ScopedFastMCP, repo: TaskHistoryRepository
    ) -> None:
        task = _make_task(task_id="reg001", is_orchestrator=False)
        repo.create(task)

        token = _set_request_ctx("reg001")
        try:
            tools = await mcp.list_tools()
            tool_names = {t.name for t in tools}

            for name in ORCHESTRATOR_TOOL_NAMES:
                assert name not in tool_names, (
                    f"Orchestrator tool '{name}' should be hidden"
                )
            # Shared tools should be present
            assert "write_result" in tool_names
            assert "load_result" in tool_names
        finally:
            _clear_request_ctx(token)

    @pytest.mark.anyio
    async def test_orchestrator_task_sees_all_tools(
        self, mcp: ScopedFastMCP, repo: TaskHistoryRepository
    ) -> None:
        task = _make_task(task_id="orch01", is_orchestrator=True)
        repo.create(task)

        token = _set_request_ctx("orch01")
        try:
            tools = await mcp.list_tools()
            tool_names = {t.name for t in tools}

            for name in TOOL_SCOPES:
                assert name in tool_names, f"Tool '{name}' should be visible"
        finally:
            _clear_request_ctx(token)

    @pytest.mark.anyio
    async def test_missing_header_hides_orchestrator_tools(
        self, mcp: ScopedFastMCP
    ) -> None:
        token = _set_request_ctx(None)
        try:
            tools = await mcp.list_tools()
            tool_names = {t.name for t in tools}

            for name in ORCHESTRATOR_TOOL_NAMES:
                assert name not in tool_names
        finally:
            _clear_request_ctx(token)


# ── ScopedFastMCP.call_tool tests ─────────────────────────────────────


class TestScopedCallTool:
    """Tests for ScopedFastMCP.call_tool guarding."""

    @pytest.fixture
    def mcp(self, repo: TaskHistoryRepository) -> ScopedFastMCP:
        from wiggy.mcp.server import _build_mcp_app

        return _build_mcp_app(repo, "proc5678")  # type: ignore[return-value]

    @pytest.mark.anyio
    async def test_regular_task_blocked_from_orchestrator_tool(
        self, mcp: ScopedFastMCP, repo: TaskHistoryRepository
    ) -> None:
        task = _make_task(task_id="reg001", is_orchestrator=False)
        repo.create(task)

        token = _set_request_ctx("reg001")
        try:
            result = await mcp.call_tool("get_process_state", {})
            assert isinstance(result, list)
            assert len(result) == 1
            assert "only available to orchestrator" in result[0].text
        finally:
            _clear_request_ctx(token)

    @pytest.mark.anyio
    async def test_orchestrator_task_can_call_orchestrator_tool(
        self, mcp: ScopedFastMCP, repo: TaskHistoryRepository
    ) -> None:
        task = _make_task(task_id="orch01", is_orchestrator=True)
        repo.create(task)

        token = _set_request_ctx("orch01")
        try:
            result = await mcp.call_tool("get_process_state", {})
            # super().call_tool returns (content_list, extras_dict)
            content = result[0] if isinstance(result, tuple) else result
            assert isinstance(content, list)
            text = content[0].text
            assert "only available to orchestrator" not in text
        finally:
            _clear_request_ctx(token)

    @pytest.mark.anyio
    async def test_missing_header_blocked_from_orchestrator_tool(
        self, mcp: ScopedFastMCP
    ) -> None:
        token = _set_request_ctx(None)
        try:
            result = await mcp.call_tool("set_process_decision", {})
            assert isinstance(result, list)
            assert "only available to orchestrator" in result[0].text
        finally:
            _clear_request_ctx(token)

    @pytest.mark.anyio
    async def test_shared_tool_accessible_by_regular_task(
        self, mcp: ScopedFastMCP, repo: TaskHistoryRepository
    ) -> None:
        task = _make_task(task_id="reg001", is_orchestrator=False)
        repo.create(task)

        token = _set_request_ctx("reg001")
        try:
            # list_artifact_templates needs no task_id, should succeed
            result = await mcp.call_tool("list_artifact_templates", {})
            content = result[0] if isinstance(result, tuple) else result
            assert isinstance(content, list)
            text = content[0].text
            parsed = json.loads(text)
            assert "templates" in parsed
        finally:
            _clear_request_ctx(token)
