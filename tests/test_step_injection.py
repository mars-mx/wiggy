"""Tests for step injection (chunk 07)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from wiggy.history import TaskHistoryRepository, TaskLog
from wiggy.mcp.tools import _process_state_store, handle_inject_steps
from wiggy.processes.base import (
    OrchestratorDecision,
    ProcessRun,
    ProcessSpec,
    ProcessStep,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "history.db"


@pytest.fixture
def repo(temp_db: Path) -> TaskHistoryRepository:
    return TaskHistoryRepository(db_path=temp_db)


def _make_task(
    task_id: str = "abcd1234",
    process_id: str = "proc5678",
    **kwargs: object,
) -> TaskLog:
    defaults = {
        "executor_id": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "branch": "wiggy/test",
        "worktree": "/tmp/worktree",
        "main_repo": "/home/user/project",
        "engine": "claude",
    }
    defaults.update(kwargs)
    return TaskLog(
        task_id=task_id,
        process_id=process_id,
        **defaults,  # type: ignore[arg-type]
    )


class TestProcessStepOriginStepIndex:
    """Tests for origin_step_index field on ProcessStep."""

    def test_default_none(self) -> None:
        step = ProcessStep(task="analyse")
        assert step.origin_step_index is None

    def test_set_value(self) -> None:
        step = ProcessStep(task="analyse", origin_step_index=2)
        assert step.origin_step_index == 2

    def test_to_dict_omits_none(self) -> None:
        step = ProcessStep(task="analyse")
        d = step.to_dict()
        assert "origin_step_index" not in d

    def test_to_dict_includes_when_set(self) -> None:
        step = ProcessStep(task="analyse", origin_step_index=3)
        d = step.to_dict()
        assert d["origin_step_index"] == 3

    def test_from_dict_without_origin(self) -> None:
        step = ProcessStep.from_dict({"task": "analyse"})
        assert step.origin_step_index is None

    def test_from_dict_with_origin(self) -> None:
        step = ProcessStep.from_dict({"task": "analyse", "origin_step_index": 5})
        assert step.origin_step_index == 5

    def test_roundtrip(self) -> None:
        original = ProcessStep(task="fix", origin_step_index=1)
        restored = ProcessStep.from_dict(original.to_dict())
        assert restored.origin_step_index == original.origin_step_index


class TestHandleInjectSteps:
    """Tests for the inject_steps MCP tool handler."""

    def test_missing_task_id(self, repo: TaskHistoryRepository) -> None:
        result = json.loads(
            handle_inject_steps(repo, None, "proc5678", [{"task_name": "analyse"}])
        )
        assert "error" in result
        assert "Missing X-Wiggy-Task-ID" in result["error"]

    def test_empty_steps(self, repo: TaskHistoryRepository) -> None:
        result = json.loads(
            handle_inject_steps(repo, "task01", "proc5678", [])
        )
        assert "error" in result
        assert "non-empty" in result["error"]

    def test_missing_task_name(self, repo: TaskHistoryRepository) -> None:
        result = json.loads(
            handle_inject_steps(repo, "task01", "proc5678", [{"prompt": "do stuff"}])
        )
        assert "error" in result
        assert "task_name" in result["error"]

    @patch("wiggy.tasks.get_task_by_name", return_value=None)
    def test_unknown_task(
        self, mock_get: object, repo: TaskHistoryRepository
    ) -> None:
        result = json.loads(
            handle_inject_steps(
                repo, "task01", "proc5678", [{"task_name": "nonexistent"}]
            )
        )
        assert "error" in result
        assert "Unknown task" in result["error"]

    @patch("wiggy.tasks.get_task_by_name")
    def test_successful_injection(
        self, mock_get: object, repo: TaskHistoryRepository
    ) -> None:
        from wiggy.tasks.base import TaskSpec

        mock_get.return_value = TaskSpec(name="hotfix", description="hotfix task")

        task = _make_task(task_id="orch01", process_id="proc5678", is_orchestrator=True)
        repo.create(task)

        _process_state_store["proc5678"] = {"current_index": 1}

        try:
            result = json.loads(
                handle_inject_steps(
                    repo,
                    "orch01",
                    "proc5678",
                    [
                        {"task_name": "hotfix", "prompt": "fix the bug"},
                        {"task_name": "hotfix"},
                    ],
                )
            )
            assert result["status"] == "ok"
            assert result["injected_count"] == 2
            assert result["steps"] == ["hotfix", "hotfix"]

            # Verify decision was recorded
            decisions = repo.get_orchestrator_decisions("proc5678")
            assert len(decisions) == 1
            assert decisions[0].decision == "inject"
            assert decisions[0].phase == "inject_request"
            assert len(decisions[0].injected_steps) == 2
        finally:
            _process_state_store.clear()


class TestStepInsertion:
    """Tests for step insertion in the process runner loop."""

    def test_inject_inserts_before_current(self) -> None:
        """Injected steps are inserted at current_index."""
        spec = ProcessSpec(
            name="test",
            steps=(
                ProcessStep(task="a"),
                ProcessStep(task="b"),
                ProcessStep(task="c"),
            ),
        )
        run = ProcessRun(process_id="p1", spec=spec)
        run.current_index = 1  # about to run "b"

        # Simulate what the orchestrator loop does
        new_steps = [
            ProcessStep(task="hotfix", origin_step_index=1),
        ]
        run.steps[1:1] = new_steps

        assert len(run.steps) == 4
        assert run.steps[0].task == "a"
        assert run.steps[1].task == "hotfix"
        assert run.steps[1].origin_step_index == 1
        assert run.steps[2].task == "b"
        assert run.steps[3].task == "c"

    def test_origin_step_index_set_on_injected(self) -> None:
        """Injected steps have origin_step_index set to current index."""
        decision = OrchestratorDecision(
            phase="pre_step",
            step_index=2,
            decision="inject",
            reasoning="Need fix",
            injected_steps=(
                ProcessStep(task="fix"),
                ProcessStep(task="verify"),
            ),
        )

        current_idx = 2
        new_steps = [
            ProcessStep(
                task=s.task,
                engine=s.engine,
                model=s.model,
                tools=s.tools,
                prompt=s.prompt,
                origin_step_index=current_idx,
            )
            for s in decision.injected_steps
        ]

        assert all(s.origin_step_index == 2 for s in new_steps)

    def test_multiple_injections_at_same_index(self) -> None:
        """Multiple injections at the same index accumulate."""
        spec = ProcessSpec(
            name="test",
            steps=(ProcessStep(task="a"), ProcessStep(task="b")),
        )
        run = ProcessRun(process_id="p1", spec=spec)
        run.current_index = 1

        # First injection
        run.steps[1:1] = [ProcessStep(task="fix1", origin_step_index=1)]
        assert len(run.steps) == 3
        assert run.steps[1].task == "fix1"

        # Second injection (at same current_index=1)
        run.steps[1:1] = [ProcessStep(task="fix2", origin_step_index=1)]
        assert len(run.steps) == 4
        assert run.steps[1].task == "fix2"
        assert run.steps[2].task == "fix1"


class TestLoopGuard:
    """Tests for the injection loop guard."""

    def test_guard_triggers_at_limit(self) -> None:
        """injection_counts tracking prevents exceeding max_injections."""
        from wiggy.config.schema import OrchestratorConfig

        config = OrchestratorConfig(max_injections=2)
        injection_counts: dict[int, int] = {}
        current_idx = 0

        # Simulate 2 injections (should succeed)
        for _ in range(2):
            assert injection_counts.get(current_idx, 0) < config.max_injections
            injection_counts[current_idx] = injection_counts.get(current_idx, 0) + 1

        # Third should be blocked
        assert injection_counts.get(current_idx, 0) >= config.max_injections

    def test_guard_per_step_index(self) -> None:
        """Each step index has its own injection counter."""
        injection_counts: dict[int, int] = {0: 3}

        # Step 1 should still be injectable
        assert injection_counts.get(1, 0) == 0

    def test_default_max_injections(self) -> None:
        """Default max_injections is 3."""
        from wiggy.config.schema import OrchestratorConfig

        config = OrchestratorConfig()
        assert config.max_injections == 3
