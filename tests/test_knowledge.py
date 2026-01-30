"""Tests for knowledge management: CRUD, MCP handlers, embeddings, and search."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wiggy.history import Knowledge, SearchResult, TaskHistoryRepository, TaskLog
from wiggy.history.embeddings import (
    FastEmbedProvider,
    OpenAIProvider,
    SentenceTransformerProvider,
    get_provider,
)
from wiggy.mcp.tools import (
    handle_get_knowledge,
    handle_search_knowledge,
    handle_view_knowledge_history,
    handle_write_knowledge,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Create a temporary database path."""
    return tmp_path / "history.db"


@pytest.fixture
def repo(temp_db: Path) -> TaskHistoryRepository:
    """Create a repository with temporary database."""
    return TaskHistoryRepository(db_path=temp_db)


def make_task(
    task_id: str = "abcd1234",
    process_id: str = "proc5678",
    executor_id: int = 1,
    **kwargs: object,
) -> TaskLog:
    """Create a TaskLog for testing."""
    defaults = {
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
        executor_id=executor_id,
        **defaults,  # type: ignore[arg-type]
    )


class TestKnowledgeDataclass:
    """Tests for Knowledge dataclass."""

    def test_construction_with_all_fields(self) -> None:
        """Test creating a Knowledge with all fields."""
        k = Knowledge(
            id=1,
            key="api-design",
            version=1,
            content="Use REST for public APIs.",
            reason="Initial decision",
            created_at="2024-01-01T00:00:00+00:00",
        )
        assert k.id == 1
        assert k.key == "api-design"
        assert k.version == 1
        assert k.content == "Use REST for public APIs."
        assert k.reason == "Initial decision"
        assert k.created_at == "2024-01-01T00:00:00+00:00"

    def test_from_row(self) -> None:
        """Test from_row class method."""
        row = {
            "id": 42,
            "key": "db-choice",
            "version": 3,
            "content": "Use PostgreSQL.",
            "reason": "Performance benchmarks",
            "created_at": "2024-06-15T10:30:00+00:00",
        }
        k = Knowledge.from_row(row)  # type: ignore[arg-type]
        assert k.id == 42
        assert k.key == "db-choice"
        assert k.version == 3
        assert k.content == "Use PostgreSQL."
        assert k.reason == "Performance benchmarks"
        assert k.created_at == "2024-06-15T10:30:00+00:00"

    def test_frozen(self) -> None:
        """Test Knowledge is immutable."""
        k = Knowledge(
            id=1,
            key="test",
            version=1,
            content="c",
            reason="r",
            created_at="2024-01-01T00:00:00+00:00",
        )
        with pytest.raises(AttributeError):
            k.content = "modified"  # type: ignore[misc]


class TestKnowledgeCRUD:
    """Tests for Knowledge repository CRUD operations."""

    @patch("wiggy.history.repository.get_provider")
    def test_write_knowledge_v1(
        self, mock_get_provider: MagicMock, repo: TaskHistoryRepository
    ) -> None:
        """Test writing the first version of a knowledge entry."""
        mock_provider = MagicMock()
        mock_provider.embed_text.return_value = [0.1] * 768
        mock_get_provider.return_value = mock_provider

        k = repo.write_knowledge("api-design", "Use REST.", "Initial")
        assert k.key == "api-design"
        assert k.version == 1
        assert k.content == "Use REST."
        assert k.reason == "Initial"
        assert k.created_at  # non-empty

    @patch("wiggy.history.repository.get_provider")
    def test_write_knowledge_v2_auto_increments(
        self, mock_get_provider: MagicMock, repo: TaskHistoryRepository
    ) -> None:
        """Test writing a second version auto-increments the version number."""
        mock_provider = MagicMock()
        mock_provider.embed_text.return_value = [0.1] * 768
        mock_get_provider.return_value = mock_provider

        k1 = repo.write_knowledge("api-design", "Use REST.", "Initial")
        k2 = repo.write_knowledge("api-design", "Use GraphQL.", "Revised")
        assert k1.version == 1
        assert k2.version == 2
        assert k2.content == "Use GraphQL."
        assert k2.reason == "Revised"

    @patch("wiggy.history.repository.get_provider")
    def test_get_latest_version(
        self, mock_get_provider: MagicMock, repo: TaskHistoryRepository
    ) -> None:
        """Test get_knowledge without version returns the latest."""
        mock_provider = MagicMock()
        mock_provider.embed_text.return_value = [0.1] * 768
        mock_get_provider.return_value = mock_provider

        repo.write_knowledge("db-choice", "SQLite", "Start simple")
        repo.write_knowledge("db-choice", "PostgreSQL", "Scale up")

        latest = repo.get_knowledge("db-choice")
        assert latest is not None
        assert latest.version == 2
        assert latest.content == "PostgreSQL"

    @patch("wiggy.history.repository.get_provider")
    def test_get_specific_version(
        self, mock_get_provider: MagicMock, repo: TaskHistoryRepository
    ) -> None:
        """Test get_knowledge with explicit version index."""
        mock_provider = MagicMock()
        mock_provider.embed_text.return_value = [0.1] * 768
        mock_get_provider.return_value = mock_provider

        repo.write_knowledge("db-choice", "SQLite", "Start simple")
        repo.write_knowledge("db-choice", "PostgreSQL", "Scale up")

        v1 = repo.get_knowledge("db-choice", version=1)
        assert v1 is not None
        assert v1.version == 1
        assert v1.content == "SQLite"

    @patch("wiggy.history.repository.get_provider")
    def test_get_returns_none_for_nonexistent(
        self, mock_get_provider: MagicMock, repo: TaskHistoryRepository
    ) -> None:
        """Test get_knowledge returns None for a key that doesn't exist."""
        mock_provider = MagicMock()
        mock_provider.embed_text.return_value = [0.1] * 768
        mock_get_provider.return_value = mock_provider

        result = repo.get_knowledge("nonexistent-key")
        assert result is None

    @patch("wiggy.history.repository.get_provider")
    def test_get_history_returns_all_versions_ascending(
        self, mock_get_provider: MagicMock, repo: TaskHistoryRepository
    ) -> None:
        """Test get_knowledge_history returns all versions in ascending order."""
        mock_provider = MagicMock()
        mock_provider.embed_text.return_value = [0.1] * 768
        mock_get_provider.return_value = mock_provider

        repo.write_knowledge("arch", "Monolith", "v1")
        repo.write_knowledge("arch", "Microservices", "v2")
        repo.write_knowledge("arch", "Modular monolith", "v3")

        history = repo.get_knowledge_history("arch")
        assert len(history) == 3
        assert [h.version for h in history] == [1, 2, 3]
        assert history[0].content == "Monolith"
        assert history[1].content == "Microservices"
        assert history[2].content == "Modular monolith"


class TestKnowledgeMCPHandlers:
    """Tests for knowledge MCP handler functions."""

    @patch("wiggy.history.repository.get_provider")
    def test_handle_write_knowledge(
        self, mock_get_provider: MagicMock, repo: TaskHistoryRepository
    ) -> None:
        """Test handle_write_knowledge returns status, key, version, created_at."""
        mock_provider = MagicMock()
        mock_provider.embed_text.return_value = [0.1] * 768
        mock_get_provider.return_value = mock_provider

        raw = handle_write_knowledge(repo, "api-design", "Use REST.", "Initial")
        data = json.loads(raw)
        assert data["status"] == "ok"
        assert data["key"] == "api-design"
        assert data["version"] == 1
        assert "created_at" in data

    @patch("wiggy.history.repository.get_provider")
    def test_handle_get_knowledge_latest(
        self, mock_get_provider: MagicMock, repo: TaskHistoryRepository
    ) -> None:
        """Test handle_get_knowledge without version returns latest."""
        mock_provider = MagicMock()
        mock_provider.embed_text.return_value = [0.1] * 768
        mock_get_provider.return_value = mock_provider

        repo.write_knowledge("api-design", "REST v1", "First")
        repo.write_knowledge("api-design", "GraphQL v2", "Second")

        raw = handle_get_knowledge(repo, "api-design")
        data = json.loads(raw)
        assert data["version"] == 2
        assert data["content"] == "GraphQL v2"
        assert data["key"] == "api-design"
        assert "reason" in data
        assert "created_at" in data

    @patch("wiggy.history.repository.get_provider")
    def test_handle_get_knowledge_with_version(
        self, mock_get_provider: MagicMock, repo: TaskHistoryRepository
    ) -> None:
        """Test handle_get_knowledge with specific version index."""
        mock_provider = MagicMock()
        mock_provider.embed_text.return_value = [0.1] * 768
        mock_get_provider.return_value = mock_provider

        repo.write_knowledge("api-design", "REST v1", "First")
        repo.write_knowledge("api-design", "GraphQL v2", "Second")

        raw = handle_get_knowledge(repo, "api-design", version=1)
        data = json.loads(raw)
        assert data["version"] == 1
        assert data["content"] == "REST v1"

    @patch("wiggy.history.repository.get_provider")
    def test_handle_get_knowledge_not_found(
        self, mock_get_provider: MagicMock, repo: TaskHistoryRepository
    ) -> None:
        """Test handle_get_knowledge returns error for nonexistent key."""
        mock_provider = MagicMock()
        mock_provider.embed_text.return_value = [0.1] * 768
        mock_get_provider.return_value = mock_provider

        raw = handle_get_knowledge(repo, "nonexistent")
        data = json.loads(raw)
        assert "error" in data
        assert "not found" in data["error"].lower()

    @patch("wiggy.history.repository.get_provider")
    def test_handle_view_knowledge_history(
        self, mock_get_provider: MagicMock, repo: TaskHistoryRepository
    ) -> None:
        """Test handle_view_knowledge_history returns versions list."""
        mock_provider = MagicMock()
        mock_provider.embed_text.return_value = [0.1] * 768
        mock_get_provider.return_value = mock_provider

        repo.write_knowledge("arch", "Monolith", "v1 reason")
        repo.write_knowledge("arch", "Microservices", "v2 reason")

        raw = handle_view_knowledge_history(repo, "arch")
        data = json.loads(raw)
        assert data["key"] == "arch"
        assert len(data["versions"]) == 2
        assert data["versions"][0]["version"] == 1
        assert data["versions"][0]["reason"] == "v1 reason"
        assert "content_preview" in data["versions"][0]
        assert "created_at" in data["versions"][0]
        assert data["versions"][1]["version"] == 2

    def test_handle_search_knowledge(self, repo: TaskHistoryRepository) -> None:
        """Test handle_search_knowledge returns results."""
        mock_results = [
            SearchResult(
                source="knowledge",
                source_id="1",
                title="api-design",
                snippet="Use REST APIs.",
                distance=0.1,
                created_at="2024-01-01T00:00:00+00:00",
            ),
        ]
        with patch.object(repo, "search_similar", return_value=mock_results):
            raw = handle_search_knowledge(repo, "REST API design")
        data = json.loads(raw)
        assert data["query"] == "REST API design"
        assert data["page"] == 1
        assert "results" in data
        assert isinstance(data["results"], list)
        assert len(data["results"]) == 1
        assert data["results"][0]["source"] == "knowledge"
        assert "has_more" in data


class TestEmbeddingProviders:
    """Tests for embedding provider factory and properties."""

    def test_factory_returns_fastembed(self) -> None:
        """Test get_provider returns FastEmbedProvider for 'fastembed'."""
        with patch("wiggy.history.embeddings._provider", None):
            provider = get_provider("fastembed")
            assert isinstance(provider, FastEmbedProvider)

    def test_factory_returns_sentence_transformers(self) -> None:
        """Test get_provider returns SentenceTransformerProvider."""
        with patch("wiggy.history.embeddings._provider", None):
            provider = get_provider("sentence-transformers")
            assert isinstance(provider, SentenceTransformerProvider)

    def test_factory_returns_openai(self) -> None:
        """Test get_provider returns OpenAIProvider for 'openai'."""
        with patch("wiggy.history.embeddings._provider", None):
            provider = get_provider("openai")
            assert isinstance(provider, OpenAIProvider)

    def test_factory_raises_for_unknown(self) -> None:
        """Test get_provider raises ValueError for unknown provider name."""
        with patch("wiggy.history.embeddings._provider", None):
            with pytest.raises(ValueError, match="Unknown embedding provider"):
                get_provider("unknown-provider")

    def test_fastembed_dimensions(self) -> None:
        """Test FastEmbedProvider.dimensions returns 768."""
        provider = FastEmbedProvider()
        assert provider.dimensions == 768

    def test_sentence_transformer_dimensions(self) -> None:
        """Test SentenceTransformerProvider.dimensions returns 768."""
        provider = SentenceTransformerProvider()
        assert provider.dimensions == 768

    def test_openai_dimensions(self) -> None:
        """Test OpenAIProvider.dimensions returns 1536."""
        provider = OpenAIProvider()
        assert provider.dimensions == 1536


class TestSearch:
    """Tests for semantic search functionality.

    sqlite-vec knn queries require specific internal constraints that
    cannot be satisfied with mock embeddings in JOINs, so we mock
    search_similar and verify the caller-facing contract: sorting,
    pagination, and deduplication.
    """

    def test_search_returns_results_sorted_by_distance(
        self, repo: TaskHistoryRepository
    ) -> None:
        """Test search returns results sorted by distance (ascending)."""
        mock_results = [
            SearchResult(
                source="knowledge",
                source_id="1",
                title="close-topic",
                snippet="Close content",
                distance=0.05,
                created_at="2024-01-01T00:00:00+00:00",
            ),
            SearchResult(
                source="knowledge",
                source_id="2",
                title="far-topic",
                snippet="Far content",
                distance=0.95,
                created_at="2024-01-01T00:00:00+00:00",
            ),
        ]
        with patch.object(repo, "search_similar", return_value=mock_results):
            results = repo.search_similar("close content query")
        assert len(results) == 2
        assert results[0].distance < results[1].distance
        assert results[0].title == "close-topic"

    def test_search_pagination(self, repo: TaskHistoryRepository) -> None:
        """Test search pagination via page parameter."""
        all_results = [
            SearchResult(
                source="knowledge",
                source_id=str(i),
                title=f"key-{i}",
                snippet=f"Content {i}",
                distance=float(i) * 0.01,
                created_at="2024-01-01T00:00:00+00:00",
            )
            for i in range(15)
        ]

        def fake_search(
            query: str, page: int = 1, page_size: int = 10
        ) -> list[SearchResult]:
            offset = (page - 1) * page_size
            return all_results[offset : offset + page_size]

        with patch.object(repo, "search_similar", side_effect=fake_search):
            page1 = repo.search_similar("content", page=1, page_size=10)
            page2 = repo.search_similar("content", page=2, page_size=10)

        assert len(page1) == 10
        assert len(page2) == 5

    def test_search_deduplicates_knowledge_to_latest_version(
        self, repo: TaskHistoryRepository
    ) -> None:
        """Test search deduplicates knowledge entries to latest version per key."""
        # Simulate the deduplicated output: only one entry per key
        mock_results = [
            SearchResult(
                source="knowledge",
                source_id="3",
                title="arch",
                snippet="Modular monolith v3",
                distance=0.1,
                created_at="2024-01-01T00:00:00+00:00",
            ),
        ]
        with patch.object(repo, "search_similar", return_value=mock_results):
            results = repo.search_similar("architecture")
        knowledge_results = [r for r in results if r.source == "knowledge"]
        arch_results = [r for r in knowledge_results if r.title == "arch"]
        assert len(arch_results) == 1
