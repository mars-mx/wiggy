"""Configuration schema and validation for wiggy."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Literal, cast

ExecutorType = Literal["docker", "shell"]
EmbeddingProviderType = Literal["fastembed", "sentence-transformers", "openai"]


@dataclass(frozen=True)
class OrchestratorConfig:
    """Configuration for the orchestrator supervisor.

    Controls whether an orchestrator reviews step outputs and can inject
    corrective steps into a running process.
    """

    enabled: bool = True
    engine: str | None = None  # defaults to process engine if None
    model: str | None = "opus"  # strongest model for supervisor
    max_injections: int = 3  # guard against infinite loops
    image: str | None = None  # override docker image

    def overlay(self, other: OrchestratorConfig) -> OrchestratorConfig:
        """Return a new config with non-None fields from `other` overlaid."""
        return OrchestratorConfig(
            enabled=other.enabled,
            engine=other.engine if other.engine is not None else self.engine,
            model=other.model if other.model is not None else self.model,
            max_injections=(
                other.max_injections
                if other.max_injections != self.max_injections
                else self.max_injections
            ),
            image=other.image if other.image is not None else self.image,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result: dict[str, Any] = {"enabled": self.enabled}
        if self.engine is not None:
            result["engine"] = self.engine
        if self.model is not None:
            result["model"] = self.model
        result["max_injections"] = self.max_injections
        if self.image is not None:
            result["image"] = self.image
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OrchestratorConfig:
        """Create from a dictionary. Unknown keys are ignored."""
        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            enabled = bool(enabled)
        engine = data.get("engine")
        model = data.get("model", "opus")
        max_injections_raw = data.get("max_injections", 3)
        max_injections = (
            int(max_injections_raw) if max_injections_raw is not None else 3
        )
        image = data.get("image")
        return cls(
            enabled=enabled,
            engine=engine,
            model=model,
            max_injections=max_injections,
            image=image,
        )


@dataclass
class WiggyConfig:
    """Wiggy configuration schema.

    All fields correspond to CLI options in `wiggy run`.
    None values indicate "not set" and will use defaults or be inherited.
    """

    # Engine settings
    engine: str | None = None
    model: str | None = None

    # Executor settings
    executor: ExecutorType | None = None
    parallel: int | None = None
    image: str | None = None

    # Worktree settings
    worktree_root: str | None = None
    keep_worktree: bool | None = None

    # Git settings
    push: bool | None = None
    pr: bool | None = None
    remote: str | None = None

    # Git author settings (for commits inside Docker containers)
    git_author_name: str | None = None
    git_author_email: str | None = None

    # Embedding settings
    embedding_provider: EmbeddingProviderType | None = None
    embedding_model: str | None = None

    # Orchestrator settings
    orchestrator: OrchestratorConfig = OrchestratorConfig()

    def merge(self, other: WiggyConfig) -> WiggyConfig:
        """Merge another config into this one.

        Values from `other` take precedence when they are not None.
        Returns a new WiggyConfig instance.
        """
        return WiggyConfig(
            engine=other.engine if other.engine is not None else self.engine,
            model=other.model if other.model is not None else self.model,
            executor=other.executor if other.executor is not None else self.executor,
            parallel=other.parallel if other.parallel is not None else self.parallel,
            image=other.image if other.image is not None else self.image,
            worktree_root=(
                other.worktree_root
                if other.worktree_root is not None
                else self.worktree_root
            ),
            keep_worktree=(
                other.keep_worktree
                if other.keep_worktree is not None
                else self.keep_worktree
            ),
            push=other.push if other.push is not None else self.push,
            pr=other.pr if other.pr is not None else self.pr,
            remote=other.remote if other.remote is not None else self.remote,
            git_author_name=(
                other.git_author_name
                if other.git_author_name is not None
                else self.git_author_name
            ),
            git_author_email=(
                other.git_author_email
                if other.git_author_email is not None
                else self.git_author_email
            ),
            embedding_provider=(
                other.embedding_provider
                if other.embedding_provider is not None
                else self.embedding_provider
            ),
            embedding_model=(
                other.embedding_model
                if other.embedding_model is not None
                else self.embedding_model
            ),
            orchestrator=self.orchestrator.overlay(other.orchestrator),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary, excluding None values."""
        result: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "orchestrator":
                result["orchestrator"] = value.to_dict()
            elif value is not None:
                result[f.name] = value
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WiggyConfig:
        """Create a WiggyConfig from a dictionary.

        Unknown keys are ignored. Type validation is performed.
        """
        valid_fields = {f.name for f in fields(cls)}

        # Extract and coerce values
        engine = data.get("engine") if "engine" in valid_fields else None
        model = data.get("model") if "model" in valid_fields else None
        executor_raw = data.get("executor")
        executor: ExecutorType | None = None
        if executor_raw in ("docker", "shell"):
            executor = cast(ExecutorType, executor_raw)
        parallel_raw = data.get("parallel")
        parallel = int(parallel_raw) if parallel_raw is not None else None
        image = data.get("image") if "image" in valid_fields else None
        worktree_root = data.get("worktree_root")
        keep_worktree_raw = data.get("keep_worktree")
        keep_worktree = (
            bool(keep_worktree_raw) if keep_worktree_raw is not None else None
        )
        push_raw = data.get("push")
        push = bool(push_raw) if push_raw is not None else None
        pr_raw = data.get("pr")
        pr = bool(pr_raw) if pr_raw is not None else None
        remote = data.get("remote")
        git_author_name = data.get("git_author_name")
        git_author_email = data.get("git_author_email")
        embedding_provider_raw = data.get("embedding_provider")
        embedding_provider: EmbeddingProviderType | None = None
        if embedding_provider_raw in ("fastembed", "sentence-transformers", "openai"):
            embedding_provider = cast(EmbeddingProviderType, embedding_provider_raw)
        embedding_model = data.get("embedding_model")

        orchestrator_raw = data.get("orchestrator")
        orchestrator = (
            OrchestratorConfig.from_dict(orchestrator_raw)
            if isinstance(orchestrator_raw, dict)
            else OrchestratorConfig()
        )

        return cls(
            engine=engine,
            model=model,
            executor=executor,
            parallel=parallel,
            image=image,
            worktree_root=worktree_root,
            keep_worktree=keep_worktree,
            push=push,
            pr=pr,
            remote=remote,
            git_author_name=git_author_name,
            git_author_email=git_author_email,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            orchestrator=orchestrator,
        )


def resolve_orchestrator_config(
    global_config: WiggyConfig,
    process_orchestrator: OrchestratorConfig | None,
) -> OrchestratorConfig:
    """Resolve the effective orchestrator config.

    Resolution order:
    1. Start with global WiggyConfig.orchestrator.
    2. If process-level orchestrator is set, overlay its non-None fields.
    """
    base = global_config.orchestrator
    if process_orchestrator is not None:
        return base.overlay(process_orchestrator)
    return base


# Default configuration values (used when not specified anywhere)
DEFAULT_CONFIG = WiggyConfig(
    executor="docker",
    parallel=1,
    keep_worktree=False,
    push=True,
    pr=True,
    remote="origin",
    embedding_provider="fastembed",
)
