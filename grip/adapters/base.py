from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None
    tool_call: ToolCall | None


@runtime_checkable
class LLMAdapter(Protocol):
    async def complete(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> LLMResponse: ...
