"""Tests for Docker executor."""

import json
from unittest.mock import MagicMock, patch

import pytest

from wiggy.engines.base import Engine
from wiggy.executors.docker import (
    MCP_CONFIG_CONTAINER_PATH,
    MCP_CONFIG_TEMPLATE,
    DockerExecutor,
)


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
def test_engine_with_mcp():
    """Create a test engine with MCP support."""
    return Engine(
        name="MCP Engine",
        cli_command="mcp-cmd",
        install_info="https://example.com",
        docker_image="test/image:latest",
        mcp_support=True,
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
    expected = "ghcr.io/mars-mx/wiggy-base:latest"
    assert executor._resolve_image(test_engine_no_image) == expected


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


# --- MCP integration tests ---


def test_mcp_config_written(mock_docker_client, test_engine_with_mcp, tmp_path) -> None:
    """Test MCP config file is written when mcp_port is set."""
    mock_container = MagicMock()
    mock_container.short_id = "abc123"
    mock_docker_client.containers.create.return_value = mock_container

    executor = DockerExecutor(mcp_port=12345)
    with patch("wiggy.executors.docker.Path.cwd", return_value=tmp_path):
        executor.setup(test_engine_with_mcp)

    config_path = tmp_path / ".wiggy" / "mcp.json"
    assert config_path.exists()


def test_mcp_config_not_written_when_no_port(
    mock_docker_client, test_engine, tmp_path
) -> None:
    """Test no MCP config file is written when mcp_port is not set."""
    mock_container = MagicMock()
    mock_container.short_id = "abc123"
    mock_docker_client.containers.create.return_value = mock_container

    executor = DockerExecutor()
    with patch("wiggy.executors.docker.Path.cwd", return_value=tmp_path):
        executor.setup(test_engine)

    config_path = tmp_path / ".wiggy" / "mcp.json"
    assert not config_path.exists()


def test_mcp_environment_variables(mock_docker_client, test_engine_with_mcp) -> None:
    """Test WIGGY_MCP_PORT and WIGGY_TASK_ID are in the container environment."""
    mock_container = MagicMock()
    mock_container.short_id = "abc123"
    mock_docker_client.containers.create.return_value = mock_container

    executor = DockerExecutor(mcp_port=12345)
    executor.set_task_id("abcd1234")
    executor.setup(test_engine_with_mcp)

    call_kwargs = mock_docker_client.containers.create.call_args.kwargs
    env = call_kwargs["environment"]
    assert env["WIGGY_MCP_PORT"] == "12345"
    assert env["WIGGY_TASK_ID"] == "abcd1234"


def test_mcp_config_mounted(mock_docker_client, test_engine_with_mcp, tmp_path) -> None:
    """Test MCP config is in volume mounts at the correct container path."""
    mock_container = MagicMock()
    mock_container.short_id = "abc123"
    mock_docker_client.containers.create.return_value = mock_container

    executor = DockerExecutor(mcp_port=12345)
    with patch("wiggy.executors.docker.Path.cwd", return_value=tmp_path):
        executor.setup(test_engine_with_mcp)

    call_kwargs = mock_docker_client.containers.create.call_args.kwargs
    volumes = call_kwargs["volumes"]
    config_host_path = str(tmp_path / ".wiggy" / "mcp.json")
    assert config_host_path in volumes
    assert volumes[config_host_path]["bind"] == MCP_CONFIG_CONTAINER_PATH
    assert volumes[config_host_path]["mode"] == "ro"


def test_mcp_config_flag_injected(mock_docker_client, test_engine_with_mcp) -> None:
    """Test --mcp-config flag is in command when mcp_port is set."""
    mock_container = MagicMock()
    mock_container.short_id = "abc123"
    mock_docker_client.containers.create.return_value = mock_container

    executor = DockerExecutor(mcp_port=12345)
    executor.setup(test_engine_with_mcp)

    call_kwargs = mock_docker_client.containers.create.call_args.kwargs
    command = call_kwargs["command"]
    assert "--mcp-config" in command
    mcp_idx = command.index("--mcp-config")
    assert command[mcp_idx + 1] == MCP_CONFIG_CONTAINER_PATH


def test_mcp_config_flag_not_injected_without_support(
    mock_docker_client, test_engine
) -> None:
    """Test --mcp-config is NOT in the command when engine.mcp_support is False."""
    mock_container = MagicMock()
    mock_container.short_id = "abc123"
    mock_docker_client.containers.create.return_value = mock_container

    executor = DockerExecutor(mcp_port=12345)
    executor.setup(test_engine)

    call_kwargs = mock_docker_client.containers.create.call_args.kwargs
    command = call_kwargs["command"]
    assert "--mcp-config" not in command


def test_mcp_config_content(mock_docker_client, test_engine_with_mcp, tmp_path) -> None:
    """Test written config file content matches the MCP template."""
    mock_container = MagicMock()
    mock_container.short_id = "abc123"
    mock_docker_client.containers.create.return_value = mock_container

    executor = DockerExecutor(mcp_port=12345)
    with patch("wiggy.executors.docker.Path.cwd", return_value=tmp_path):
        executor.setup(test_engine_with_mcp)

    config_path = tmp_path / ".wiggy" / "mcp.json"
    content = json.loads(config_path.read_text())

    assert content == MCP_CONFIG_TEMPLATE
    # Verify the placeholders are present as literal strings
    wiggy_server = content["mcpServers"]["wiggy"]
    assert "${WIGGY_MCP_PORT}" in wiggy_server["url"]
    assert wiggy_server["headers"]["X-Wiggy-Task-ID"] == "${WIGGY_TASK_ID}"
