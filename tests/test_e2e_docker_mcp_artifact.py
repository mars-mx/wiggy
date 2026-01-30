"""End-to-end test: Docker container writes an artifact via the MCP server."""

import json
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import docker
import pytest

from wiggy.history import TaskHistoryRepository, TaskLog
from wiggy.mcp.networking import resolve_mcp_bind_host
from wiggy.mcp.server import WiggyMCPServer


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

# ---------------------------------------------------------------------------
# Minimal MCP client script (runs inside the Docker container using only
# Python stdlib).  It performs the MCP streamable-HTTP handshake and then
# calls the ``write_artifact`` tool, printing the tool result JSON to stdout.
# ---------------------------------------------------------------------------
MCP_CLIENT_SCRIPT = textwrap.dedent(r"""
    import json, os, sys
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError

    PORT = os.environ["WIGGY_MCP_PORT"]
    TASK_ID = os.environ["WIGGY_TASK_ID"]
    URL = f"http://host.docker.internal:{PORT}/mcp"

    def post(payload):
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
            "X-Wiggy-Task-ID": TASK_ID,
        }
        data = json.dumps(payload).encode()
        req = Request(URL, data=data, headers=headers)
        try:
            with urlopen(req, timeout=15) as resp:
                ct = resp.headers.get("Content-Type", "")
                body = resp.read().decode()
                if "text/event-stream" in ct:
                    # Parse SSE – collect all data: lines per event block
                    result = None
                    for line in body.split("\n"):
                        if line.startswith("data: "):
                            result = json.loads(line[6:])
                    return result
                elif body.strip():
                    return json.loads(body)
                return None
        except HTTPError as e:
            # 202 Accepted is expected for notifications
            if e.code in (200, 202, 204):
                return None
            body = e.read().decode()
            print(f"HTTP {e.code}: {body}", file=sys.stderr)
            sys.exit(1)

    # 1. MCP initialize handshake
    init = post({
        "jsonrpc": "2.0", "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "e2e-test", "version": "1.0"},
        },
    })
    print(f"init ok: {init is not None}", file=sys.stderr)

    # 2. Send initialized notification
    post({"jsonrpc": "2.0", "method": "notifications/initialized"})
    print("initialized sent", file=sys.stderr)

    # 3. Call write_artifact tool
    resp = post({
        "jsonrpc": "2.0", "id": 2,
        "method": "tools/call",
        "params": {
            "name": "write_artifact",
            "arguments": {
                "title": "E2E Docker Artifact",
                "content": "# E2E Test\nWritten from Docker container via MCP.",
                "format": "markdown",
                "tags": ["e2e", "docker"],
            },
        },
    })

    # Extract tool result text from MCP JSON-RPC response
    content_items = resp.get("result", {}).get("content", [])
    tool_text = ""
    for item in content_items:
        if item.get("type") == "text":
            tool_text = item.get("text", "")
            break

    # Output to stdout for the test harness to capture
    print(tool_text)
""").lstrip()


@pytest.mark.integration
class TestDockerMCPEndToEnd:
    """End-to-end: Docker container writes an artifact via MCP HTTP."""

    def test_container_writes_artifact_via_mcp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A Docker container calls the MCP server to write an artifact."""
        monkeypatch.chdir(tmp_path)

        # --- Setup: database and task record ---
        db_path = tmp_path / "history.db"
        repo = TaskHistoryRepository(db_path=db_path)

        task_id = "e2e00001"
        process_id = "proce2e1"
        task = TaskLog(
            task_id=task_id,
            process_id=process_id,
            executor_id=1,
            created_at=datetime.now(UTC).isoformat(),
            branch="wiggy/e2e-mcp-test",
            worktree=str(tmp_path),
            main_repo=str(tmp_path),
            engine="echo",
        )
        repo.create(task)

        # --- Start MCP server on Docker-reachable host ---
        bind_host = resolve_mcp_bind_host()
        mcp_server = WiggyMCPServer(repo=repo, process_id=process_id, host=bind_host)
        mcp_port = mcp_server.start()
        assert mcp_port > 0

        client = docker.from_env()
        container = None
        try:
            # --- Run MCP client script inside Docker container ---
            container = client.containers.run(
                "python:3.12-alpine",
                command=["python3", "-c", MCP_CLIENT_SCRIPT],
                environment={
                    "WIGGY_MCP_PORT": str(mcp_port),
                    "WIGGY_TASK_ID": task_id,
                },
                extra_hosts={"host.docker.internal": "host-gateway"},
                detach=True,
            )
            result = container.wait(timeout=60)
            stdout = container.logs(stdout=True, stderr=False).decode().strip()
            stderr = container.logs(stdout=False, stderr=True).decode().strip()

            assert result.get("StatusCode") == 0, (
                f"Container exited with code {result.get('StatusCode')}.\n"
                f"stderr: {stderr}\nstdout: {stdout}"
            )

            # --- Verify MCP tool response ---
            tool_result = json.loads(stdout)
            assert tool_result["status"] == "ok"
            artifact_id = tool_result["artifact_id"]
            assert tool_result["title"] == "E2E Docker Artifact"

            # --- Verify artifact persisted in database ---
            artifact = repo.get_artifact_by_id(artifact_id)
            assert artifact is not None
            assert artifact.title == "E2E Docker Artifact"
            assert artifact.format == "markdown"
            assert "# E2E Test" in artifact.content
            assert "e2e" in artifact.tags
            assert "docker" in artifact.tags

            # Verify via task-level lookup
            artifacts = repo.get_artifacts_by_task_id(task_id)
            assert len(artifacts) == 1
            assert artifacts[0].id == artifact_id

        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except docker.errors.NotFound:
                    pass
            client.close()
            mcp_server.stop()
