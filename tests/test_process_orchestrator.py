"""Tests for process orchestrator."""

from __future__ import annotations

from wiggy.processes.base import ProcessRun, ProcessSpec, ProcessStep, StepResult
from wiggy.processes.orchestrator import build_process_status_prompt


def _make_spec(
    name: str = "test-process",
    description: str = "A test process.",
    steps: tuple[ProcessStep, ...] | None = None,
) -> ProcessSpec:
    """Create a ProcessSpec for testing."""
    if steps is None:
        steps = (
            ProcessStep(task="analyze"),
            ProcessStep(task="implement"),
            ProcessStep(task="review"),
        )
    return ProcessSpec(name=name, steps=steps, description=description)


def _make_run(
    spec: ProcessSpec | None = None,
    current_index: int = 0,
    results: list[StepResult] | None = None,
) -> ProcessRun:
    """Create a ProcessRun for testing."""
    if spec is None:
        spec = _make_spec()
    run = ProcessRun(process_id="deadbeef", spec=spec)
    run.current_index = current_index
    if results:
        run.results = results
    return run


class TestBuildProcessStatusPrompt:
    """Tests for build_process_status_prompt."""

    def test_header_present(self) -> None:
        run = _make_run()
        result = build_process_status_prompt(run)
        assert "You are running as part of a multi-step process." in result

    def test_mcp_tools_mentioned(self) -> None:
        run = _make_run()
        result = build_process_status_prompt(run)
        assert "read_result_summary" in result
        assert "write_result" in result

    def test_process_name_and_description(self) -> None:
        spec = _make_spec(name="my-process", description="Does things.")
        run = _make_run(spec=spec)
        result = build_process_status_prompt(run)
        assert "## Process: my-process" in result
        assert "Does things." in result

    def test_first_step_is_current(self) -> None:
        run = _make_run(current_index=0)
        result = build_process_status_prompt(run)
        assert "1. analyze [CURRENT (you are here)]" in result
        assert "2. implement [PENDING]" in result
        assert "3. review [PENDING]" in result

    def test_middle_step_is_current(self) -> None:
        results = [
            StepResult(
                step_index=0,
                task_name="analyze",
                task_id="aaa11111",
                success=True,
                exit_code=0,
                duration_ms=1000,
            ),
        ]
        run = _make_run(current_index=1, results=results)
        result = build_process_status_prompt(run)
        assert "1. analyze [COMPLETED]" in result
        assert "2. implement [CURRENT (you are here)]" in result
        assert "3. review [PENDING]" in result

    def test_last_step_is_current(self) -> None:
        results = [
            StepResult(
                step_index=0,
                task_name="analyze",
                task_id="aaa11111",
                success=True,
                exit_code=0,
                duration_ms=1000,
            ),
            StepResult(
                step_index=1,
                task_name="implement",
                task_id="bbb22222",
                success=True,
                exit_code=0,
                duration_ms=2000,
            ),
        ]
        run = _make_run(current_index=2, results=results)
        result = build_process_status_prompt(run)
        assert "1. analyze [COMPLETED]" in result
        assert "2. implement [COMPLETED]" in result
        assert "3. review [CURRENT (you are here)]" in result

    def test_current_step_shown_at_end(self) -> None:
        run = _make_run(current_index=1)
        result = build_process_status_prompt(run)
        assert result.endswith("Current step: implement")

    def test_single_step_process(self) -> None:
        spec = _make_spec(steps=(ProcessStep(task="only-task"),))
        run = _make_run(spec=spec)
        result = build_process_status_prompt(run)
        assert "1. only-task [CURRENT (you are here)]" in result
        assert "Current step: only-task" in result

    def test_no_summaries_without_repo(self) -> None:
        """Without a repo, the Completed Step Summaries section is omitted."""
        results = [
            StepResult(
                step_index=0,
                task_name="analyze",
                task_id="aaa11111",
                success=True,
                exit_code=0,
                duration_ms=1000,
            ),
        ]
        run = _make_run(current_index=1, results=results)
        result = build_process_status_prompt(run)
        assert "## Completed Step Summaries:" not in result
