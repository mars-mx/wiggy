"""Base artifact template definition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ArtifactTemplate:
    """Definition of an artifact template.

    Templates define the structure and format for artifacts produced
    during task execution (e.g., PRDs, documentation, ADRs).
    """

    name: str  # e.g. "prd", "documentation", "adr"
    description: str
    format: str  # "json" | "markdown" | "xml" | "text"
    content: str  # The template body/structure
    tags: tuple[str, ...] = ()  # Default tags
    source: Path | None = None  # Path where template was loaded from
