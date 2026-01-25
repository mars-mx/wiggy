"""Base task definition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TaskSpec:
    """Definition of a task type for AI execution.

    A task specifies how the AI should approach a chunk of work,
    including the prompt, available tools, and model preferences.
    """

    name: str
    description: str
    tools: tuple[str, ...] = ("*",)  # Tool allowlist ("*" = all)
    model: str | None = None  # Model preference (optional)
    prompt_template: str = ""  # Combined markdown prompt
    source: Path | None = None  # Path where task was loaded from

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
        }
        if self.tools != ("*",):
            result["tools"] = list(self.tools)
        if self.model is not None:
            result["model"] = self.model
        # prompt_template and source are runtime-only, not serialized
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: Path | None = None) -> TaskSpec:
        """Create TaskSpec from dictionary (parsed task.yaml)."""
        name = str(data.get("name", ""))
        description = str(data.get("description", ""))

        tools_raw = data.get("tools", ["*"])
        if isinstance(tools_raw, list):
            tools = tuple(str(t) for t in tools_raw)
        else:
            tools = ("*",)

        model = data.get("model")
        if model is not None:
            model = str(model)

        return cls(
            name=name,
            description=description,
            tools=tools,
            model=model,
            prompt_template="",  # Set by loader after reading .md files
            source=source,
        )

    def with_prompt(self, prompt_template: str) -> TaskSpec:
        """Return a new TaskSpec with the prompt_template set."""
        return TaskSpec(
            name=self.name,
            description=self.description,
            tools=self.tools,
            model=self.model,
            prompt_template=prompt_template,
            source=self.source,
        )
