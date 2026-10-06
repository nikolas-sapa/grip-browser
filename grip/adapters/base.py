from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class LLMUsage:
    """Provider-reported categories, never estimates or a billing total.

    Anthropic input excludes cache counts; OpenAI/Gemini input includes cache.
    Thought tokens remain a separate category; do not sum categories blindly.
    """

    provider: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    thought_tokens: int | None = None
    total_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LLMProtocolError(ValueError):
    """Invalid model response with any reported usage retained for accounting."""

    def __init__(self, message: str, usage: LLMUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


def _reported_count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


@dataclass
class LLMResponse:
    content: str | None
    tool_call: ToolCall | None
    usage: LLMUsage | None = None
    replay_metadata: dict[str, Any] | None = None


@runtime_checkable
class LLMAdapter(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse: ...
