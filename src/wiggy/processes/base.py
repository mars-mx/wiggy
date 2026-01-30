"""Base process definition."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wiggy.git.worktree import WorktreeInfo


@dataclass
class ProcessStep:
    """A single step within a process, referencing a task with optional overrides.

    Mutable to allow future dynamic task injection.
    """

    task: str
    engine: str | None = None
    model: str | None = None
    tools: tuple[str, ...] | None = None
    prompt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None fields."""
        result: dict[str, Any] = {"task": self.task}
        if self.engine is not None:
            result["engine"] = self.engine
        if self.model is not None:
            result["model"] = self.model
        if self.tools is not None:
            result["tools"] = list(self.tools)
        if self.prompt is not None:
            result["prompt"] = self.prompt
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProcessStep:
        """Deserialize from dict, converting tools list to tuple if present."""
        tools_raw = data.get("tools")
        tools: tuple[str, ...] | None = None
        if tools_raw is not None:
            if isinstance(tools_raw, (list, tuple)):
                tools = tuple(str(t) for t in tools_raw)
            else:
                tools = None

        return cls(
            task=str(data["task"]),
            engine=data.get("engine"),
            model=data.get("model"),
            tools=tools,
            prompt=data.get("prompt"),
        )


@dataclass(frozen=True)
class ProcessSpec:
    """Immutable specification of a process — an ordered sequence of steps.

    Represents the on-disk format of a process definition.
    """

    name: str
    steps: tuple[ProcessStep, ...]
    description: str = ""
    source: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, excluding source."""
        result: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps],
        }
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: Path | None = None) -> ProcessSpec:
        """Deserialize from dict."""
        steps_raw = data.get("steps", [])
        steps = tuple(ProcessStep.from_dict(s) for s in steps_raw)
        return cls(
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            steps=steps,
            source=source,
        )


@dataclass(frozen=True)
class StepResult:
    """Result of executing a single process step."""

    step_index: int
    task_name: str
    task_id: str
    success: bool
    exit_code: int
    duration_ms: int


@dataclass
class ProcessRun:
    """Runtime state for an executing process.

    Separates mutable runtime state from the immutable on-disk spec.
    """

    process_id: str
    spec: ProcessSpec
    steps: list[ProcessStep] = field(init=False)
    results: list[StepResult] = field(default_factory=list)
    current_index: int = 0
    worktree_info: WorktreeInfo | None = None

    def __post_init__(self) -> None:
        self.steps = list(self.spec.steps)
