"""Result compression via Claude Haiku subprocess."""

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a technical summarizer. Produce a TLDR summary of the following task result.

Include:
1. A 2-3 sentence executive summary
2. Key decisions or findings as bullet points
3. Relevant source code locations as file:line references

Keep the entire output under 500 tokens. Be precise and actionable.\
 Focus on relevant files over a long text.\
"""


class CompressionError(Exception):
    """Raised when result compression fails."""

    pass


def is_compression_available() -> bool:
    """Check if the claude CLI is available for compression."""
    return shutil.which("claude") is not None


def compress_result(result_text: str, timeout: int = 60) -> str:
    """Spawn claude with haiku to compress a result into a summary.

    All tools and MCP servers are explicitly disabled to prevent
    unintended side effects — this is a pure summarization call.

    Args:
        result_text: The full result text to compress.
        timeout: Maximum seconds to wait for compression.

    Returns:
        The compressed summary text.

    Raises:
        CompressionError: If compression fails for any reason.
    """
    cmd = [
        "claude",
        "--model",
        "haiku",
        "--print",
        "--no-tool",
        "--mcp-tool-pattern",
        "",
        "--system-prompt",
        SYSTEM_PROMPT,
    ]

    try:
        result = subprocess.run(
            cmd,
            input=result_text,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        result.check_returncode()
    except subprocess.TimeoutExpired as err:
        raise CompressionError(f"Compression timed out after {timeout}s") from err
    except subprocess.CalledProcessError as exc:
        raise CompressionError(f"Compression failed: {exc.stderr}") from exc
    except FileNotFoundError as err:
        raise CompressionError("claude CLI not found") from err

    return result.stdout.strip()
