"""Configuration schema and validation for wiggy."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Literal, cast

ExecutorType = Literal["docker", "shell"]
EmbeddingProviderType = Literal["fastembed", "sentence-transformers", "openai"]


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

    # Embedding settings
    embedding_provider: EmbeddingProviderType | None = None
    embedding_model: str | None = None

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
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary, excluding None values."""
        result: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if value is not None:
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
        embedding_provider_raw = data.get("embedding_provider")
        embedding_provider: EmbeddingProviderType | None = None
        if embedding_provider_raw in ("fastembed", "sentence-transformers", "openai"):
            embedding_provider = cast(EmbeddingProviderType, embedding_provider_raw)
        embedding_model = data.get("embedding_model")

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
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
        )


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
