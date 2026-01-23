"""Parsed message types for engine output."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageType(Enum):
    """Types of parsed messages."""

    # Wiggy internal messages (from entrypoint, system)
    WIGGY_LOG = "wiggy_log"
    WIGGY_ERROR = "wiggy_error"

    # Claude-specific message types
    SYSTEM_INIT = "system_init"
    ASSISTANT = "assistant"
    USER = "user"
    RESULT = "result"
    STREAM_EVENT = "stream_event"

    # Fallback for unrecognized output
    RAW = "raw"


@dataclass(frozen=True)
class ParsedMessage:
    """A parsed message from engine output."""

    message_type: MessageType
    content: str  # Human-readable content to display
    raw: str  # Original raw line
    metadata: dict[str, Any] = field(default_factory=dict)

    # Optional fields for specific message types
    is_error: bool = False
    is_final: bool = False  # True for result messages


@dataclass(frozen=True)
class SessionSummary:
    """Summary extracted from a completed session."""

    session_id: str | None = None
    model: str | None = None
    total_cost: float | None = None
    duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    success: bool = True
    error_message: str | None = None
