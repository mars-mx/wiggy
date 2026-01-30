"""Integration test: Docker container spawn + artifact creation from template."""

import json
from datetime import datetime, timezone
from pathlib import Path

import docker
import pytest

from wiggy.engines.base import Engine
from wiggy.executors.docker import DockerExecutor
from wiggy.history import TaskHistoryRepository, TaskLog
from wiggy.mcp.server import WiggyMCPServer
from wiggy.mcp.tools import handle_load_artifact_template, handle_write_artifact
from wiggy.templates.loader import get_package_templates_path, load_template_from_dir


def _docker_available() -> bool:
    """Check whether Docker daemon is reachable."""
    try:
        client = docker.from_env()
        client.ping()
        client.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(),
    reason="Docker daemon not available",
)

# Minimal engine that just runs `echo` inside alpine
ECHO_ENGINE = Engine(
    name="echo",
    cli_command="echo",
    install_info="n/a",
    docker_image="alpine:latest",
    mcp_support=False,
)


@pytest.mark.integration
class TestDockerArtifactIntegration:
    """Integration: spawn Docker container, then create artifact from template."""

    def test_spawn_container_and_create_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Spawn a Docker container and create an artifact from the PRD template."""
        monkeypatch.chdir(tmp_path)

        # --- Setup: database and task record ---
        db_path = tmp_path / "history.db"
        repo = TaskHistoryRepository(db_path=db_path)

        task_id = "intg0001"
        process_id = "proc0001"
        task = TaskLog(
            task_id=task_id,
            process_id=process_id,
            executor_id=1,
            created_at=datetime.now(timezone.utc).isoformat(),
            branch="wiggy/integration-test",
            worktree=str(tmp_path),
            main_repo=str(tmp_path),
            engine="echo",
        )
        repo.create(task)

        # --- Phase 1: Docker smoke — spawn a real container ---
        executor = DockerExecutor(
            image_override="alpine:latest",
            quiet=True,
            mount_cwd=False,
        )
        executor.set_task_id(task_id)

        try:
            executor.setup(ECHO_ENGINE, prompt="hello from wiggy")
            messages = list(executor.run())
            assert executor.exit_code == 0

            output_text = " ".join(m.content for m in messages if m.content)
            assert "hello" in output_text.lower()
        finally:
            executor.teardown()

        # --- Phase 2: MCP server + artifact from template ---
        # Make package templates discoverable via handler
        monkeypatch.setattr(
            "wiggy.mcp.tools.get_template_by_name",
            lambda name: load_template_from_dir(get_package_templates_path() / name),
        )

        mcp_server = WiggyMCPServer(repo=repo, process_id=process_id)
        port = mcp_server.start()
        assert port > 0

        try:
            # Load the built-in PRD template
            template_json = json.loads(handle_load_artifact_template("prd"))
            assert "error" not in template_json
            assert template_json["name"] == "prd"
            template_content = template_json["content"]
            template_format = template_json["format"]

            # Write artifact using the template content
            result_json = json.loads(
                handle_write_artifact(
                    repo,
                    task_id=task_id,
                    title="PRD: Integration Test Feature",
                    content=template_content,
                    fmt=template_format,
                    template_name="prd",
                    tags=["integration-test", "prd"],
                )
            )
            assert result_json["status"] == "ok"
            artifact_id = result_json["artifact_id"]

            # Verify artifact persisted in database
            artifact = repo.get_artifact_by_id(artifact_id)
            assert artifact is not None
            assert artifact.title == "PRD: Integration Test Feature"
            assert artifact.format == "markdown"
            assert artifact.template_name == "prd"
            assert artifact.content == template_content
            assert "integration-test" in artifact.tags

            # Verify task's artifact list
            artifacts = repo.get_artifacts_by_task_id(task_id)
            assert len(artifacts) == 1
            assert artifacts[0].id == artifact_id
        finally:
            mcp_server.stop()
