"""Tests for Docker executor."""

from unittest.mock import MagicMock, patch

import pytest

from wiggy.engines.base import Engine
from wiggy.executors.docker import DockerExecutor


@pytest.fixture
def mock_docker_client():
    """Create a mock Docker client."""
    with patch("wiggy.executors.docker.docker") as mock_docker:
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_docker.errors = MagicMock()
        mock_docker.errors.NotFound = Exception
        yield mock_client


@pytest.fixture
def test_engine():
    """Create a test engine."""
    return Engine(
        name="Test Engine",
        cli_command="test-cmd",
        install_info="https://example.com",
        docker_image="test/image:latest",
    )


@pytest.fixture
def test_engine_no_image():
    """Create a test engine without docker_image."""
    return Engine(
        name="No Image Engine",
        cli_command="cmd",
        install_info="url",
    )


def test_docker_executor_name() -> None:
    """Test executor has correct name."""
    executor = DockerExecutor()
    assert executor.name == "docker"


def test_docker_executor_initial_exit_code() -> None:
    """Test initial exit code is None."""
    executor = DockerExecutor()
    assert executor.exit_code is None


def test_resolve_image_override(test_engine) -> None:
    """Test image override takes precedence."""
    executor = DockerExecutor(image_override="custom/image:v1")
    assert executor._resolve_image(test_engine) == "custom/image:v1"


def test_resolve_image_engine_default(test_engine) -> None:
    """Test engine default image is used when no override."""
    executor = DockerExecutor()
    assert executor._resolve_image(test_engine) == "test/image:latest"


def test_resolve_image_fallback(test_engine_no_image) -> None:
    """Test fallback to base image when no engine image."""
    executor = DockerExecutor()
    assert executor._resolve_image(test_engine_no_image) == "ghcr.io/mars-mx/wiggy-base:latest"


def test_setup_creates_container(mock_docker_client, test_engine) -> None:
    """Test setup creates a Docker container."""
    mock_container = MagicMock()
    mock_container.short_id = "abc123"
    mock_docker_client.containers.create.return_value = mock_container

    executor = DockerExecutor()
    executor.setup(test_engine)

    mock_docker_client.containers.create.assert_called_once()
    call_kwargs = mock_docker_client.containers.create.call_args.kwargs
    assert call_kwargs["command"] == ["test-cmd"]
    assert call_kwargs["working_dir"] == "/workspace"
    assert call_kwargs["tty"] is True


def test_run_without_setup_raises() -> None:
    """Test run raises error if setup not called."""
    executor = DockerExecutor()
    with pytest.raises(RuntimeError, match="setup\\(\\) must be called"):
        list(executor.run())


def test_teardown_removes_container(mock_docker_client, test_engine) -> None:
    """Test teardown removes the container."""
    mock_container = MagicMock()
    mock_container.short_id = "abc123"
    mock_docker_client.containers.create.return_value = mock_container

    executor = DockerExecutor()
    executor.setup(test_engine)
    executor.teardown()

    mock_container.remove.assert_called_once_with(force=True)
