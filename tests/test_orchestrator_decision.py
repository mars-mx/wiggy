"""Tests for OrchestratorDecision model and repository methods."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from wiggy.history import TaskHistoryRepository, TaskLog
from wiggy.processes.base import OrchestratorDecision, ProcessStep


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


class TestOrchestratorDecisionDataclass:
    """Tests for the OrchestratorDecision dataclass."""

    def test_create_basic(self) -> None:
        d = OrchestratorDecision(
            phase="pre_step",
            step_index=0,
            decision="proceed",
            reasoning="All good",
        )
        assert d.phase == "pre_step"
        assert d.step_index == 0
        assert d.decision == "proceed"
        assert d.reasoning == "All good"
        assert d.injected_steps == ()
        assert d.task_id == ""
        assert d.created_at == ""

    def test_frozen(self) -> None:
        d = OrchestratorDecision(
            phase="post_step",
            step_index=1,
            decision="abort",
            reasoning="Failed",
        )
        with pytest.raises(AttributeError):
            d.phase = "finalize"  # type: ignore[misc]

    def test_with_injected_steps(self) -> None:
        steps = (
            ProcessStep(task="hotfix", engine="claude"),
            ProcessStep(task="retest"),
        )
        d = OrchestratorDecision(
            phase="post_step",
            step_index=2,
            decision="inject",
            reasoning="Need hotfix",
            injected_steps=steps,
            task_id="orch0001",
            created_at="2025-01-01T00:00:00Z",
        )
        assert len(d.injected_steps) == 2
        assert d.injected_steps[0].task == "hotfix"
        assert d.injected_steps[0].engine == "claude"
        assert d.injected_steps[1].task == "retest"


class TestProcessRunOrchestratorDecisions:
    """Tests for orchestrator_decisions field on ProcessRun."""

    def test_default_empty(self) -> None:
        from wiggy.processes.base import ProcessRun, ProcessSpec

        spec = ProcessSpec(name="p", steps=(ProcessStep(task="a"),))
        run = ProcessRun(process_id="abc", spec=spec)
        assert run.orchestrator_decisions == []

    def test_append(self) -> None:
        from wiggy.processes.base import ProcessRun, ProcessSpec

        spec = ProcessSpec(name="p", steps=(ProcessStep(task="a"),))
        run = ProcessRun(process_id="abc", spec=spec)
        d = OrchestratorDecision(
            phase="pre_step", step_index=0, decision="proceed", reasoning="ok"
        )
        run.orchestrator_decisions.append(d)
        assert len(run.orchestrator_decisions) == 1


class TestTaskLogIsOrchestrator:
    """Tests for the is_orchestrator field on TaskLog."""

    def test_default_false(self) -> None:
        task = _make_task()
        assert task.is_orchestrator is False

    def test_set_true(self) -> None:
        task = _make_task(is_orchestrator=True)
        assert task.is_orchestrator is True

    def test_persisted_and_retrieved(self, repo: TaskHistoryRepository) -> None:
        task = _make_task(is_orchestrator=True)
        repo.create(task)
        retrieved = repo.get_by_task_id("abcd1234")
        assert retrieved is not None
        assert retrieved.is_orchestrator is True

    def test_default_persisted_as_false(
        self, repo: TaskHistoryRepository
    ) -> None:
        task = _make_task()
        repo.create(task)
        retrieved = repo.get_by_task_id("abcd1234")
        assert retrieved is not None
        assert retrieved.is_orchestrator is False


class TestOrchestratorDecisionRepository:
    """Tests for orchestrator decision repository methods."""

    def test_save_and_get(self, repo: TaskHistoryRepository) -> None:
        task = _make_task()
        repo.create(task)

        d = OrchestratorDecision(
            phase="pre_step",
            step_index=0,
            decision="proceed",
            reasoning="Looks good",
            task_id="abcd1234",
            created_at="2025-01-01T00:00:00Z",
        )
        repo.save_orchestrator_decision("proc5678", d)

        decisions = repo.get_orchestrator_decisions("proc5678")
        assert len(decisions) == 1
        assert decisions[0].phase == "pre_step"
        assert decisions[0].step_index == 0
        assert decisions[0].decision == "proceed"
        assert decisions[0].reasoning == "Looks good"
        assert decisions[0].task_id == "abcd1234"
        assert decisions[0].created_at == "2025-01-01T00:00:00Z"
        assert decisions[0].injected_steps == ()

    def test_save_with_injected_steps(
        self, repo: TaskHistoryRepository
    ) -> None:
        task = _make_task()
        repo.create(task)

        steps = (
            ProcessStep(task="hotfix", engine="claude", model="opus"),
            ProcessStep(task="retest"),
        )
        d = OrchestratorDecision(
            phase="post_step",
            step_index=1,
            decision="inject",
            reasoning="Need hotfix first",
            injected_steps=steps,
            task_id="abcd1234",
            created_at="2025-01-01T00:00:00Z",
        )
        repo.save_orchestrator_decision("proc5678", d)

        decisions = repo.get_orchestrator_decisions("proc5678")
        assert len(decisions) == 1
        assert decisions[0].decision == "inject"
        assert len(decisions[0].injected_steps) == 2
        assert decisions[0].injected_steps[0].task == "hotfix"
        assert decisions[0].injected_steps[0].engine == "claude"
        assert decisions[0].injected_steps[0].model == "opus"
        assert decisions[0].injected_steps[1].task == "retest"

    def test_multiple_decisions_ordered(
        self, repo: TaskHistoryRepository
    ) -> None:
        task = _make_task()
        repo.create(task)

        for i in range(3):
            d = OrchestratorDecision(
                phase="pre_step",
                step_index=i,
                decision="proceed",
                reasoning=f"Step {i} ok",
                task_id="abcd1234",
                created_at=f"2025-01-01T0{i}:00:00Z",
            )
            repo.save_orchestrator_decision("proc5678", d)

        decisions = repo.get_orchestrator_decisions("proc5678")
        assert len(decisions) == 3
        assert [d.step_index for d in decisions] == [0, 1, 2]

    def test_get_empty(self, repo: TaskHistoryRepository) -> None:
        decisions = repo.get_orchestrator_decisions("nonexistent")
        assert decisions == []

    def test_decisions_scoped_to_process(
        self, repo: TaskHistoryRepository
    ) -> None:
        task1 = _make_task(task_id="task0001", process_id="procAAAA")
        task2 = _make_task(task_id="task0002", process_id="procBBBB")
        repo.create(task1)
        repo.create(task2)

        d1 = OrchestratorDecision(
            phase="pre_step",
            step_index=0,
            decision="proceed",
            reasoning="ok",
            task_id="task0001",
            created_at="2025-01-01T00:00:00Z",
        )
        d2 = OrchestratorDecision(
            phase="pre_step",
            step_index=0,
            decision="abort",
            reasoning="bad",
            task_id="task0002",
            created_at="2025-01-01T00:00:00Z",
        )
        repo.save_orchestrator_decision("procAAAA", d1)
        repo.save_orchestrator_decision("procBBBB", d2)

        assert len(repo.get_orchestrator_decisions("procAAAA")) == 1
        assert len(repo.get_orchestrator_decisions("procBBBB")) == 1
        assert repo.get_orchestrator_decisions("procAAAA")[0].decision == "proceed"
        assert repo.get_orchestrator_decisions("procBBBB")[0].decision == "abort"
