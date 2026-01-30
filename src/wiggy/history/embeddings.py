"""Embedding providers for semantic search over task history."""

from __future__ import annotations

from typing import Any, Protocol


class EmbeddingProvider(Protocol):
    """Protocol for embedding text into dense vectors."""

    @property
    def dimensions(self) -> int: ...

    def embed_text(self, text: str) -> list[float]: ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedProvider:
    """Embedding provider using fastembed (default)."""

    def __init__(self, model: str = "BAAI/bge-base-en-v1.5") -> None:
        self._model_name = model
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    @property
    def dimensions(self) -> int:
        return 768

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        embeddings = list(model.embed(texts))
        return [e.tolist() for e in embeddings]


class SentenceTransformerProvider:
    """Embedding provider using sentence-transformers."""

    def __init__(self, model: str = "nomic-ai/nomic-embed-text-v1.5") -> None:
        self._model_name = model
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import (
                SentenceTransformer,
            )

            self._model = SentenceTransformer(self._model_name)
        return self._model

    @property
    def dimensions(self) -> int:
        return 768

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        embeddings = model.encode(texts)
        return [e.tolist() for e in embeddings]


class OpenAIProvider:
    """Embedding provider using OpenAI's API."""

    def __init__(self, model: str = "text-embedding-3-small") -> None:
        self._model_name = model
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import openai  # type: ignore[import-not-found]

            self._client = openai.OpenAI()
        return self._client

    @property
    def dimensions(self) -> int:
        return 1536

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        response = client.embeddings.create(
            input=texts,
            model=self._model_name,
        )
        return [item.embedding for item in response.data]


_provider: EmbeddingProvider | None = None


def get_provider(
    provider_name: str = "fastembed",
    model: str | None = None,
) -> EmbeddingProvider:
    """Get or create the singleton embedding provider."""
    global _provider
    if _provider is None:
        match provider_name:
            case "fastembed":
                _provider = FastEmbedProvider(model or "BAAI/bge-base-en-v1.5")
            case "sentence-transformers":
                _provider = SentenceTransformerProvider(
                    model or "nomic-ai/nomic-embed-text-v1.5"
                )
            case "openai":
                _provider = OpenAIProvider(model or "text-embedding-3-small")
            case _:
                raise ValueError(f"Unknown embedding provider: {provider_name}")
    return _provider
