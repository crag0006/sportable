"""What the assistant needs from a chat model and an embedding model, and nothing more."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    """One ``tool_use`` block the model emitted."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ModelReply:
    """One assistant turn: its text, its tool calls, why it stopped, what it cost."""

    text: str
    tool_calls: tuple[ToolCall, ...]
    stop_reason: str
    content: list[dict[str, Any]] = field(default_factory=list)  # to send back verbatim
    input_tokens: int = 0
    output_tokens: int = 0


class ChatModel(Protocol):
    """A tool-using chat model behind the Anthropic Messages API shape."""

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, Any],
        max_tokens: int,
    ) -> ModelReply:
        """One model call; raises ``ModelUnavailableError`` when the model cannot be reached."""
        ...


class EmbeddingModel(Protocol):
    """A text embedding model."""

    def embed(self, text: str) -> list[float]:
        """The vector for one text; raises ``ModelUnavailableError`` when it cannot be reached."""
        ...


class ModelUnavailableError(RuntimeError):
    """The model could not be called (network, throttle, permissions, timeout)."""
