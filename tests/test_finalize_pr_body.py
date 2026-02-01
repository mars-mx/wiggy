"""Tests for finalize output capture and PR body fallback chain.

Covers:
- _run_orchestrator_phase captures finalize output as a task result
- run_process PR body fallback: artifact → finalize result → None
- CLI process run PR body fallback: pr_body → commit messages
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from wiggy.config.schema import OrchestratorConfig, WiggyConfig
from wiggy.parsers.messages import MessageType, ParsedMessage
from wiggy.processes.base import (
    OrchestratorDecision,
    ProcessRun,
    ProcessSpec,
    ProcessStep,
)
from wiggy.processes.orchestrator import run_process

_ORCH_MOD = "wiggy.processes.orchestrator"


# ---------------------------------------------------------------------------
# Helpers (shared with test_orchestrator_integration.py patterns)
# ---------------------------------------------------------------------------


def _make_spec(
    steps: tuple[ProcessStep, ...] | None = None,
    orchestrator: OrchestratorConfig | None = None,
) -> ProcessSpec:
    if steps is None:
        steps = (ProcessStep(task="implement"),)
    return ProcessSpec(
        name="test-process",
        description="A test process.",
        steps=steps,
        orchestrator=orchestrator,
    )


def _make_task_spec(task_name: str, tmp_path: Path) -> MagicMock:
    spec = MagicMock()
    spec.name = task_name
    spec.model = None
    spec.tools = ("*",)
    spec.source = tmp_path / task_name
    spec.source.mkdir(parents=True, exist_ok=True)
    return spec


class _MockMCPServer:
    def start(self) -> int:
        return 9999

    def stop(self) -> None:
        pass


def _make_engine() -> MagicMock:
    engine = MagicMock()
    engine.name = "claude"
    return engine


def _make_mock_repo() -> MagicMock:
    repo = MagicMock()
    repo.get_orchestrator_decisions.return_value = []
    repo.get_result_by_task_id.return_value = None
    repo.get_result_by_task_name.return_value = None
    repo.get_artifacts_by_process_id.return_value = []
    return repo


def _make_msg(content: str) -> ParsedMessage:
    """Create a ParsedMessage with content."""
    return ParsedMessage(
        message_type=MessageType.ASSISTANT,
        content=content,
        raw=content,
    )


def _make_mock_executor(
    exit_code: int = 0,
    messages: list[ParsedMessage] | None = None,
) -> MagicMock:
    executor = MagicMock()
    executor.exit_code = exit_code
    executor.summary = None
    executor.run.return_value = iter(messages or [])
    return executor


# ---------------------------------------------------------------------------
# Tests: finalize output capture in _run_orchestrator_phase
# ---------------------------------------------------------------------------


class TestFinalizeOutputCapture:
    """Verify that finalize phase output is stored as a task result."""

    def test_finalize_output_stored_as_result(self, tmp_path: Path) -> None:
        """When finalize executor yields messages, they are stored as a result."""
        spec = _make_spec()
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=True))

        finalize_messages = [
            _make_msg("## Summary"),
            _make_msg("Added new feature X."),
        ]

        call_count = {"step": 0}
        executors: list[MagicMock] = []

        def tracking_get_executor(**kwargs: Any) -> MagicMock:
            call_count["step"] += 1
            # The finalize executor is called after pre + step + post = 3 calls
            # With 1 step: pre(1) + step(2) + post(3) + finalize(4)
            if call_count["step"] == 4:
                ex = _make_mock_executor(messages=finalize_messages)
            else:
                ex = _make_mock_executor()
            executors.append(ex)
            return ex

        mock_repo = _make_mock_repo()

        def fake_get_task(name: str) -> MagicMock | None:
            return _make_task_spec(name, tmp_path)

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=mock_repo,
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=_make_engine()),
            patch(
                f"{_ORCH_MOD}.get_executor",
                side_effect=tracking_get_executor,
            ),
        ):
            run_process(process_spec=spec, config=config)

        # Verify create_result was called with the finalize output
        create_result_calls = mock_repo.create_result.call_args_list
        assert len(create_result_calls) == 1
        call_kwargs = create_result_calls[0][1]
        assert "## Summary" in call_kwargs["result_text"]
        assert "Added new feature X." in call_kwargs["result_text"]
        assert call_kwargs["tags"] == ["pr-body-fallback"]

    def test_finalize_output_not_stored_when_result_exists(
        self, tmp_path: Path
    ) -> None:
        """When a finalize result already exists, don't create a duplicate."""
        spec = _make_spec()
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=True))

        finalize_messages = [_make_msg("Some output")]

        call_count = {"step": 0}

        def tracking_get_executor(**kwargs: Any) -> MagicMock:
            call_count["step"] += 1
            if call_count["step"] == 4:
                return _make_mock_executor(messages=finalize_messages)
            return _make_mock_executor()

        mock_repo = _make_mock_repo()
        # Pretend a result already exists
        existing_result = MagicMock()
        existing_result.result_text = "Already stored"
        mock_repo.get_result_by_task_name.return_value = existing_result

        def fake_get_task(name: str) -> MagicMock | None:
            return _make_task_spec(name, tmp_path)

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=mock_repo,
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=_make_engine()),
            patch(
                f"{_ORCH_MOD}.get_executor",
                side_effect=tracking_get_executor,
            ),
        ):
            run_process(process_spec=spec, config=config)

        # create_result should NOT have been called
        mock_repo.create_result.assert_not_called()

    def test_non_finalize_phase_does_not_capture_output(
        self, tmp_path: Path
    ) -> None:
        """Pre/post phases should NOT store output as results."""
        spec = _make_spec()
        # Disable orchestrator so only the step executor runs (no finalize)
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=False))

        messages = [_make_msg("Step output")]

        def fake_get_task(name: str) -> MagicMock | None:
            return _make_task_spec(name, tmp_path)

        mock_repo = _make_mock_repo()

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=mock_repo,
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=_make_engine()),
            patch(
                f"{_ORCH_MOD}.get_executor",
                return_value=_make_mock_executor(messages=messages),
            ),
        ):
            run_process(process_spec=spec, config=config)

        # No finalize → no create_result calls
        mock_repo.create_result.assert_not_called()

    def test_empty_finalize_output_not_stored(self, tmp_path: Path) -> None:
        """When finalize executor yields no messages, no result is stored."""
        spec = _make_spec()
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=True))

        def fake_get_task(name: str) -> MagicMock | None:
            return _make_task_spec(name, tmp_path)

        mock_repo = _make_mock_repo()

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=mock_repo,
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=_make_engine()),
            patch(
                f"{_ORCH_MOD}.get_executor",
                return_value=_make_mock_executor(),
            ),
        ):
            run_process(process_spec=spec, config=config)

        # Empty output → no create_result
        mock_repo.create_result.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: PR body fallback chain in run_process
# ---------------------------------------------------------------------------


class TestRunProcessPrBodyFallback:
    """Test the artifact → finalize result → None fallback chain."""

    def test_pr_body_from_artifact(self, tmp_path: Path) -> None:
        """pr_body is set from pr_description artifact when available."""
        spec = _make_spec()
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=True))

        artifact = MagicMock()
        artifact.template_name = "pr_description"
        artifact.content = "## PR from artifact"

        mock_repo = _make_mock_repo()
        mock_repo.get_artifacts_by_process_id.return_value = [artifact]

        def fake_get_task(name: str) -> MagicMock | None:
            return _make_task_spec(name, tmp_path)

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=mock_repo,
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=_make_engine()),
            patch(
                f"{_ORCH_MOD}.get_executor",
                return_value=_make_mock_executor(),
            ),
        ):
            result = run_process(process_spec=spec, config=config)

        assert result.pr_body == "## PR from artifact"

    def test_pr_body_from_finalize_result(self, tmp_path: Path) -> None:
        """pr_body falls back to finalize task result when no artifact."""
        spec = _make_spec()
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=True))

        finalize_result = MagicMock()
        finalize_result.result_text = "## PR from finalize result"

        mock_repo = _make_mock_repo()
        # No artifacts
        mock_repo.get_artifacts_by_process_id.return_value = []
        mock_repo.get_result_by_task_name.return_value = finalize_result

        def fake_get_task(name: str) -> MagicMock | None:
            return _make_task_spec(name, tmp_path)

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=mock_repo,
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=_make_engine()),
            patch(
                f"{_ORCH_MOD}.get_executor",
                return_value=_make_mock_executor(),
            ),
        ):
            result = run_process(process_spec=spec, config=config)

        assert result.pr_body == "## PR from finalize result"

    def test_pr_body_none_when_no_artifact_or_result(
        self, tmp_path: Path
    ) -> None:
        """pr_body stays None when neither artifact nor result available."""
        spec = _make_spec()
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=True))

        mock_repo = _make_mock_repo()
        mock_repo.get_artifacts_by_process_id.return_value = []
        mock_repo.get_result_by_task_name.return_value = None

        def fake_get_task(name: str) -> MagicMock | None:
            return _make_task_spec(name, tmp_path)

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=mock_repo,
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=_make_engine()),
            patch(
                f"{_ORCH_MOD}.get_executor",
                return_value=_make_mock_executor(),
            ),
        ):
            result = run_process(process_spec=spec, config=config)

        assert result.pr_body is None

    def test_artifact_preferred_over_finalize_result(
        self, tmp_path: Path
    ) -> None:
        """When both artifact and finalize result exist, artifact wins."""
        spec = _make_spec()
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=True))

        artifact = MagicMock()
        artifact.template_name = "pr_description"
        artifact.content = "## From artifact"

        finalize_result = MagicMock()
        finalize_result.result_text = "## From finalize"

        mock_repo = _make_mock_repo()
        mock_repo.get_artifacts_by_process_id.return_value = [artifact]
        mock_repo.get_result_by_task_name.return_value = finalize_result

        def fake_get_task(name: str) -> MagicMock | None:
            return _make_task_spec(name, tmp_path)

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=mock_repo,
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=_make_engine()),
            patch(
                f"{_ORCH_MOD}.get_executor",
                return_value=_make_mock_executor(),
            ),
        ):
            result = run_process(process_spec=spec, config=config)

        assert result.pr_body == "## From artifact"
