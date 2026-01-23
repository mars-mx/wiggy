"""Docker executor implementation."""

from collections.abc import Iterator

import docker
from docker.models.containers import Container

from wiggy.console import console
from wiggy.engines.base import Engine
from wiggy.executors.base import Executor


class DockerExecutor(Executor):
    """Executor that runs engines in Docker containers."""

    name = "docker"

    def __init__(self, image_override: str | None = None) -> None:
        self._image_override = image_override
        self._client: docker.DockerClient | None = None
        self._container: Container | None = None
        self._engine: Engine | None = None
        self._exit_code: int | None = None

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

    def setup(self, engine: Engine) -> None:
        """Set up the Docker container for the given engine."""
        self._engine = engine
        client = self._get_client()

        image = self._resolve_image(engine)
        console.print(f"[dim]Using image: {image}[/dim]")

        # Create container with project mounted
        self._container = client.containers.create(
            image=image,
            command=engine.cli_command,
            working_dir="/workspace",
            tty=True,
            stdin_open=True,
            detach=True,
        )

        console.print(f"[dim]Created container: {self._container.short_id}[/dim]")

    def run(self) -> Iterator[str]:
        """Run the engine in a Docker container.

        Yields stdout lines as they are produced.
        """
        if self._container is None:
            raise RuntimeError("setup() must be called before run()")

        self._container.start()

        # Stream logs in real-time
        for chunk in self._container.logs(stream=True, follow=True):
            line = chunk.decode("utf-8", errors="replace")
            yield line.rstrip("\n")

        # Wait for container to finish and get exit code
        result = self._container.wait()
        self._exit_code = result.get("StatusCode", 1)

    def teardown(self) -> None:
        """Clean up the Docker container."""
        if self._container is not None:
            try:
                self._container.remove(force=True)
                console.print(
                    f"[dim]Removed container: {self._container.short_id}[/dim]"
                )
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
