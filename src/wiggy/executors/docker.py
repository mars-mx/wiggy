"""Docker executor implementation."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import docker
from docker.models.containers import Container

from wiggy.console import console
from wiggy.engines.base import Engine
from wiggy.executors.base import Executor
from wiggy.parsers import get_parser_for_engine
from wiggy.parsers.base import Parser
from wiggy.parsers.messages import ParsedMessage, SessionSummary

if TYPE_CHECKING:
    from wiggy.git import WorktreeInfo

# Mount point for credentials inside container
CREDENTIALS_MOUNT = "/mnt/credentials"

# Mount point for MCP config inside container
MCP_CONFIG_CONTAINER_PATH = "/home/wiggy/.wiggy/mcp.json"

# MCP config template with env var placeholders for client-side expansion
MCP_CONFIG_TEMPLATE = {
    "mcpServers": {
        "wiggy": {
            "type": "http",
            "url": "http://host.docker.internal:${WIGGY_MCP_PORT}/mcp",
            "headers": {"X-Wiggy-Task-ID": "${WIGGY_TASK_ID}"},
        }
    }
}


class DockerExecutor(Executor):
    """Executor that runs engines in Docker containers."""

    name = "docker"

    def __init__(
        self,
        image_override: str | None = None,
        model_override: str | None = None,
        executor_id: int = 1,
        quiet: bool = False,
        worktree_info: WorktreeInfo | None = None,
        extra_args: tuple[str, ...] = (),
        allowed_tools: list[str] | None = None,
        mount_cwd: bool = False,
        global_tasks_rw: bool = False,
        mcp_port: int | None = None,
    ) -> None:
        self._image_override = image_override
        self._model_override = model_override
        self.executor_id = executor_id
        self.quiet = quiet
        self._worktree_info = worktree_info
        self._extra_args = extra_args
        self._allowed_tools = allowed_tools
        self._mount_cwd = mount_cwd
        self._global_tasks_rw = global_tasks_rw
        self._mcp_port = mcp_port
        self._mcp_config_path: Path | None = None
        self._client: docker.DockerClient | None = None
        self._container: Container | None = None
        self._engine: Engine | None = None
        self._exit_code: int | None = None
        self._parser: Parser | None = None

    def _get_client(self) -> docker.DockerClient:
        """Get or create Docker client."""
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def _resolve_image(self, engine: Engine) -> str:
        """Resolve which Docker image to use."""
        if self._image_override:
            return self._image_override
        if engine.docker_image:
            return engine.docker_image
        return "ghcr.io/mars-mx/wiggy-base:latest"

    def _write_mcp_config(self) -> Path:
        """Write the MCP config template to .wiggy/mcp.json.

        Returns the host path to the config file.
        The file uses ${WIGGY_MCP_PORT} and ${WIGGY_TASK_ID} for env var
        expansion by the MCP client at runtime.
        """
        if self._mcp_config_path is not None:
            return self._mcp_config_path

        config_path = Path.cwd() / ".wiggy" / "mcp.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(MCP_CONFIG_TEMPLATE, indent=4) + "\n")
        return config_path

    def _get_volume_mounts(self, engine: Engine) -> dict[str, dict[str, str]]:
        """Build volume mount configuration from credential_dir and worktree."""
        volumes: dict[str, dict[str, str]] = {}

        # Mount worktree as /workspace (read-write for git commits)
        if self._worktree_info:
            volumes[str(self._worktree_info.path)] = {
                "bind": "/workspace",
                "mode": "rw",
            }
            # Mount the main repo's .git directory at the same host path
            # This allows the worktree's .git file reference to work inside container
            main_git_dir = self._worktree_info.main_repo / ".git"
            if main_git_dir.exists():
                volumes[str(main_git_dir)] = {
                    "bind": str(main_git_dir),
                    "mode": "rw",
                }
        elif self._mount_cwd:
            # Mount cwd as /workspace when no worktree (for task creation/execution)
            cwd = Path.cwd()
            volumes[str(cwd)] = {
                "bind": "/workspace",
                "mode": "rw",
            }

        # Mount global tasks directory
        global_tasks = Path.home() / ".wiggy" / "tasks"
        if global_tasks.exists():
            volumes[str(global_tasks)] = {
                "bind": "/home/wiggy/.wiggy/tasks",
                "mode": "rw" if self._global_tasks_rw else "ro",
            }

        # Mount credentials (read-only)
        if engine.credential_dir:
            cred_path = Path(engine.credential_dir).expanduser()
            if cred_path.exists():
                volumes[str(cred_path)] = {
                    "bind": CREDENTIALS_MOUNT,
                    "mode": "ro",
                }

        # Mount MCP config (if MCP enabled)
        if self._mcp_config_path:
            volumes[str(self._mcp_config_path)] = {
                "bind": MCP_CONFIG_CONTAINER_PATH,
                "mode": "ro",
            }

        return volumes

    def _get_environment(self) -> dict[str, str]:
        """Build environment variables for container."""
        env: dict[str, str] = {}
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key
        if self._mcp_port is not None:
            env["WIGGY_MCP_PORT"] = str(self._mcp_port)
        if self._task_id:
            env["WIGGY_TASK_ID"] = self._task_id
        return env

    def _build_command(self, engine: Engine, prompt: str | None) -> list[str]:
        """Build the full command list for the engine."""
        command = [engine.cli_command]
        if self._model_override:
            command.extend(["--model", self._model_override])
        # Add allowed tools if specified (not "*" which means all)
        if self._allowed_tools is not None and self._allowed_tools != ["*"]:
            command.extend(["--allowedTools", ",".join(self._allowed_tools)])
        # Inject --mcp-config when MCP is enabled and engine supports it
        if self._mcp_port is not None and engine.mcp_support:
            command.extend(["--mcp-config", MCP_CONFIG_CONTAINER_PATH])
        # Add extra args (e.g., --append-system-prompt)
        command.extend(self._extra_args)
        command.extend(engine.default_args)
        if prompt:
            command.append(prompt)
        return command

    def _pull_image(self, client: docker.DockerClient, image: str) -> None:
        """Pull the Docker image if not available locally."""
        try:
            client.images.get(image)
            if not self.quiet:
                console.print(f"[dim]Image found locally: {image}[/dim]")
        except docker.errors.ImageNotFound:
            if not self.quiet:
                console.print(f"[dim]Pulling image: {image}[/dim]")
            client.images.pull(image)
            if not self.quiet:
                console.print(f"[dim]Pulled image: {image}[/dim]")

    def setup(self, engine: Engine, prompt: str | None = None) -> None:
        """Set up the Docker container for the given engine."""
        self._engine = engine
        client = self._get_client()

        image = self._resolve_image(engine)
        self._pull_image(client, image)

        # Write MCP config if MCP enabled
        if self._mcp_port is not None:
            self._mcp_config_path = self._write_mcp_config()

        volumes = self._get_volume_mounts(engine)
        environment = self._get_environment()
        command = self._build_command(engine, prompt)

        self._container = client.containers.create(
            image=image,
            command=command,
            working_dir="/workspace",
            tty=True,
            stdin_open=True,
            detach=True,
            volumes=volumes if volumes else None,
            environment=environment if environment else None,
        )

        if not self.quiet:
            console.print(f"[dim]Created container: {self._container.short_id}[/dim]")
            console.print(f"[dim]Command: {' '.join(command)}[/dim]")

        # Open log file for raw output
        self._open_log()

    def run(self) -> Iterator[ParsedMessage]:
        """Run the engine in a Docker container.

        Yields ParsedMessage objects as they are produced.
        """
        if self._container is None or self._engine is None:
            raise RuntimeError("setup() must be called before run()")

        # Get parser for this engine
        self._parser = get_parser_for_engine(self._engine.name)

        self._container.start()

        # Stream logs in real-time, buffering into lines
        buffer = ""
        for chunk in self._container.logs(stream=True, follow=True):
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                self._write_log(line)
                yield self._parser.parse_line(line)

        # Yield any remaining content
        if buffer:
            self._write_log(buffer)
            yield self._parser.parse_line(buffer)

        # Wait for container to finish and get exit code
        result = self._container.wait()
        self._exit_code = result.get("StatusCode", 1)

    def teardown(self) -> None:
        """Clean up the Docker container."""
        self._close_log()

        if self._container is not None:
            try:
                short_id = self._container.short_id
                self._container.remove(force=True)
                if not self.quiet:
                    console.print(f"[dim]Removed container: {short_id}[/dim]")
            except docker.errors.NotFound:
                pass  # Already removed
            self._container = None

        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def exit_code(self) -> int | None:
        """Return the exit code after run() completes, or None if still running."""
        return self._exit_code

    @property
    def summary(self) -> SessionSummary | None:
        """Return the session summary after run() completes, or None if unavailable."""
        if self._parser is None:
            return None
        return self._parser.get_summary()
