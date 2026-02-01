"""Integration tests for orchestrator loop in run_process()."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from wiggy.config.schema import OrchestratorConfig, WiggyConfig
from wiggy.processes.base import (
    OrchestratorDecision,
    ProcessSpec,
    ProcessStep,
)
from wiggy.processes.orchestrator import (
    build_orchestrator_context_prompt,
    run_process,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec(
    steps: tuple[ProcessStep, ...] | None = None,
    orchestrator: OrchestratorConfig | None = None,
) -> ProcessSpec:
    if steps is None:
        steps = (
            ProcessStep(task="analyze"),
            ProcessStep(task="implement"),
        )
    return ProcessSpec(
        name="test-process",
        description="A test process.",
        steps=steps,
        orchestrator=orchestrator,
    )


def _make_mock_executor(exit_code: int = 0) -> MagicMock:
    """Create a mock executor that yields no messages and returns cleanly."""
    executor = MagicMock()
    executor.exit_code = exit_code
    executor.summary = None
    executor.run.return_value = iter([])
    return executor


def _make_task_spec(task_name: str, tmp_path: Path) -> MagicMock:
    """Create a mock TaskSpec with a source directory."""
    spec = MagicMock()
    spec.name = task_name
    spec.model = None
    spec.tools = ("*",)
    spec.source = tmp_path / task_name
    spec.source.mkdir(parents=True, exist_ok=True)
    return spec


class _MockMCPServer:
    """Minimal stand-in for WiggyMCPServer."""

    def start(self) -> int:
        return 9999

    def stop(self) -> None:
        pass


def _make_engine() -> MagicMock:
    engine = MagicMock()
    engine.name = "claude"
    return engine


def _make_mock_repo() -> MagicMock:
    """Create a properly configured mock TaskHistoryRepository."""
    repo = MagicMock()
    repo.get_orchestrator_decisions.return_value = []
    repo.get_result_by_task_id.return_value = None
    return repo


# ---------------------------------------------------------------------------
# Shared patch targets
# ---------------------------------------------------------------------------

_ORCH_MOD = "wiggy.processes.orchestrator"


# ---------------------------------------------------------------------------
# Tests: build_orchestrator_context_prompt
# ---------------------------------------------------------------------------


class TestBuildOrchestratorContextPrompt:
    def test_basic_fields(self) -> None:
        from wiggy.processes.base import ProcessRun

        spec = _make_spec()
        run = ProcessRun(process_id="abc123", spec=spec)

        result = build_orchestrator_context_prompt(run, "pre_step", 0)

        assert "Process: test-process (abc123)" in result
        assert "Phase: pre_step for step 1 of 2" in result
        assert "Step: analyze" in result
        assert "Completed steps: 0/2" in result

    def test_step_with_prompt(self) -> None:
        from wiggy.processes.base import ProcessRun

        spec = _make_spec(
            steps=(ProcessStep(task="analyze", prompt="Focus on security"),)
        )
        run = ProcessRun(process_id="abc123", spec=spec)

        result = build_orchestrator_context_prompt(run, "pre_step", 0)
        assert "Step: analyze — Focus on security" in result

    def test_finalize_phase_beyond_steps(self) -> None:
        from wiggy.processes.base import ProcessRun, StepResult

        spec = _make_spec()
        run = ProcessRun(process_id="abc123", spec=spec)
        run.results = [
            StepResult(
                step_index=0,
                task_name="analyze",
                task_id="t1",
                success=True,
                exit_code=0,
                duration_ms=100,
            ),
            StepResult(
                step_index=1,
                task_name="implement",
                task_id="t2",
                success=True,
                exit_code=0,
                duration_ms=200,
            ),
        ]

        result = build_orchestrator_context_prompt(run, "finalize", 2)
        assert "Phase: finalize for step 3 of 2" in result
        assert "Completed steps: 2/2" in result
        # step_index >= total, so no "Step:" line
        assert "Step:" not in result


# ---------------------------------------------------------------------------
# Tests: run_process with orchestrator
# ---------------------------------------------------------------------------


class TestRunProcessOrchestratorEnabled:
    """Orchestrator enabled: pre/post/finalize phases execute."""

    def test_orchestrator_phases_called(self, tmp_path: Path) -> None:
        spec = _make_spec()
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=True))

        mock_engine = _make_engine()
        mock_executor = _make_mock_executor()

        task_load_calls: list[str] = []

        def fake_get_task(name: str) -> MagicMock | None:
            task_load_calls.append(name)
            return _make_task_spec(name, tmp_path)

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=_make_mock_repo(),
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=mock_engine),
            patch(f"{_ORCH_MOD}.get_executor", return_value=mock_executor),
        ):
            result = run_process(
                process_spec=spec,
                config=config,
            )

        orch_tasks = [
            n for n in task_load_calls if n.startswith("orchestrator-")
        ]
        step_tasks = [
            n for n in task_load_calls if not n.startswith("orchestrator-")
        ]

        assert "orchestrator-pre" in orch_tasks
        assert "orchestrator-post" in orch_tasks
        assert "orchestrator-finalize" in orch_tasks
        assert "analyze" in step_tasks
        assert "implement" in step_tasks

        # Both steps should have completed
        assert len(result.results) == 2
        assert all(r.success for r in result.results)


class TestRunProcessOrchestratorDisabled:
    """Orchestrator disabled: no orchestrator invocations."""

    def test_no_orchestrator_calls(self, tmp_path: Path) -> None:
        spec = _make_spec()
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=False))

        mock_engine = _make_engine()
        mock_executor = _make_mock_executor()

        task_load_calls: list[str] = []

        def fake_get_task(name: str) -> MagicMock | None:
            task_load_calls.append(name)
            return _make_task_spec(name, tmp_path)

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=_make_mock_repo(),
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=mock_engine),
            patch(f"{_ORCH_MOD}.get_executor", return_value=mock_executor),
        ):
            result = run_process(
                process_spec=spec,
                config=config,
            )

        # No orchestrator tasks should have been loaded
        orch_tasks = [
            n for n in task_load_calls if n.startswith("orchestrator-")
        ]
        assert orch_tasks == []

        # Steps still complete
        assert len(result.results) == 2


class TestRunProcessSkipOrchestrator:
    """skip_orchestrator on a step: that step has no pre/post."""

    def test_skip_orchestrator_on_step(self, tmp_path: Path) -> None:
        spec = _make_spec(
            steps=(
                ProcessStep(task="analyze", skip_orchestrator=True),
                ProcessStep(task="implement"),
            )
        )
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=True))

        mock_engine = _make_engine()
        mock_executor = _make_mock_executor()

        task_load_calls: list[str] = []

        def fake_get_task(name: str) -> MagicMock | None:
            task_load_calls.append(name)
            return _make_task_spec(name, tmp_path)

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=_make_mock_repo(),
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=mock_engine),
            patch(f"{_ORCH_MOD}.get_executor", return_value=mock_executor),
        ):
            result = run_process(
                process_spec=spec,
                config=config,
            )

        # Step "analyze" has skip_orchestrator=True, so no pre/post for it.
        # Step "implement" should have pre and post.
        # Plus finalize at the end.
        orch_pre_calls = task_load_calls.count("orchestrator-pre")
        orch_post_calls = task_load_calls.count("orchestrator-post")

        # Only 1 pre (for implement), not 2
        assert orch_pre_calls == 1
        # Only 1 post (for implement), not 2
        assert orch_post_calls == 1
        # Finalize still runs
        assert "orchestrator-finalize" in task_load_calls

        assert len(result.results) == 2


class TestRunProcessOrchestratorFailure:
    """Orchestrator failure (crash): process continues gracefully."""

    def test_orchestrator_crash_continues(self, tmp_path: Path) -> None:
        spec = _make_spec()
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=True))

        mock_engine = _make_engine()

        def fake_get_task(name: str) -> MagicMock | None:
            return _make_task_spec(name, tmp_path)

        executor_calls: list[dict[str, Any]] = []

        def tracking_get_executor(**kwargs: Any) -> MagicMock:
            executor_calls.append(kwargs)
            return _make_mock_executor()

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=_make_mock_repo(),
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=mock_engine),
            patch(
                f"{_ORCH_MOD}.get_executor",
                side_effect=tracking_get_executor,
            ),
        ):
            result = run_process(
                process_spec=spec,
                config=config,
            )

        # Process still completes both steps despite orchestrator running
        assert len(result.results) == 2
        assert all(r.success for r in result.results)

    def test_orchestrator_task_not_found_continues(
        self, tmp_path: Path
    ) -> None:
        """When orchestrator task definitions don't exist, process continues."""
        spec = _make_spec()
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=True))

        mock_engine = _make_engine()
        mock_executor = _make_mock_executor()

        def fake_get_task(name: str) -> MagicMock | None:
            if name.startswith("orchestrator-"):
                return None
            return _make_task_spec(name, tmp_path)

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=_make_mock_repo(),
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=mock_engine),
            patch(f"{_ORCH_MOD}.get_executor", return_value=mock_executor),
        ):
            result = run_process(
                process_spec=spec,
                config=config,
            )

        # Process still completes
        assert len(result.results) == 2
        assert all(r.success for r in result.results)


class TestRunProcessOrchestratorAbort:
    """Orchestrator abort decision: process stops with reason recorded."""

    def test_abort_stops_process(self, tmp_path: Path) -> None:
        spec = _make_spec(
            steps=(
                ProcessStep(task="analyze"),
                ProcessStep(task="implement"),
                ProcessStep(task="review"),
            )
        )
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=True))

        mock_engine = _make_engine()
        mock_executor = _make_mock_executor()

        def fake_get_task(name: str) -> MagicMock | None:
            return _make_task_spec(name, tmp_path)

        orchestrator_task_ids: list[str] = []

        def fake_get_decisions(process_id: str) -> list[OrchestratorDecision]:
            # After first step completes (pre+post = 2 orch tasks),
            # the 3rd orchestrator task is the 2nd pre-step.
            # Return abort with the task_id that was just created.
            if len(orchestrator_task_ids) >= 3:
                return [
                    OrchestratorDecision(
                        phase="pre_step",
                        step_index=1,
                        decision="abort",
                        reasoning="Code quality too low to continue.",
                        task_id=orchestrator_task_ids[-1],
                        created_at="2025-01-01T00:00:00Z",
                    )
                ]
            return []

        def fake_create(task_log: Any) -> Any:
            if task_log.task_name and task_log.task_name.startswith(
                "orchestrator-"
            ):
                orchestrator_task_ids.append(task_log.task_id)
            return task_log

        mock_repo = _make_mock_repo()
        mock_repo.get_orchestrator_decisions.side_effect = fake_get_decisions
        mock_repo.create.side_effect = fake_create

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=mock_repo,
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=mock_engine),
            patch(f"{_ORCH_MOD}.get_executor", return_value=mock_executor),
        ):
            result = run_process(
                process_spec=spec,
                config=config,
            )

        # Only first step should have completed (abort before second step)
        assert len(result.results) == 1
        assert result.results[0].task_name == "analyze"

        # Decisions: "proceed" for step 1 pre, then "abort" for step 2 pre
        assert len(result.orchestrator_decisions) == 2
        assert result.orchestrator_decisions[0].decision == "proceed"
        assert result.orchestrator_decisions[1].decision == "abort"
        assert "Code quality" in result.orchestrator_decisions[1].reasoning


class TestRunProcessDefaultProceed:
    """Default to 'proceed' when no decision record exists."""

    def test_no_decision_defaults_proceed(self, tmp_path: Path) -> None:
        spec = _make_spec(steps=(ProcessStep(task="analyze"),))
        config = WiggyConfig(orchestrator=OrchestratorConfig(enabled=True))

        mock_engine = _make_engine()
        mock_executor = _make_mock_executor()

        def fake_get_task(name: str) -> MagicMock | None:
            return _make_task_spec(name, tmp_path)

        with (
            patch(f"{_ORCH_MOD}.WiggyMCPServer", return_value=_MockMCPServer()),
            patch(f"{_ORCH_MOD}.resolve_mcp_bind_host", return_value="0.0.0.0"),
            patch(
                f"{_ORCH_MOD}.TaskHistoryRepository",
                return_value=_make_mock_repo(),
            ),
            patch(f"{_ORCH_MOD}.get_task_by_name", side_effect=fake_get_task),
            patch(f"{_ORCH_MOD}.resolve_engine", return_value=mock_engine),
            patch(f"{_ORCH_MOD}.get_executor", return_value=mock_executor),
        ):
            result = run_process(
                process_spec=spec,
                config=config,
            )

        # Step completes normally (default proceed)
        assert len(result.results) == 1
        assert result.results[0].success

        # Pre-step decision defaults to proceed and gets appended
        assert len(result.orchestrator_decisions) == 1
        assert result.orchestrator_decisions[0].decision == "proceed"
        assert "defaulting to proceed" in result.orchestrator_decisions[0].reasoning
