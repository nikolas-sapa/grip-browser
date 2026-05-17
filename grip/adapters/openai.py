from __future__ import annotations
import json
from typing import Any

try:
    import openai as openai
except ImportError:
    openai = None

from grip.adapters.base import LLMResponse, ToolCall


class OpenAIAdapter:
    def __init__(self, api_key: str | None = None, model: str = "gpt-4o") -> None:
        if openai is None:
            raise ImportError("pip install grip-browser[openai]")
        self._client = openai.AsyncOpenAI(api_key=api_key)
        self._model = model

    async def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        kwargs: dict[str, Any] = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            return LLMResponse(
                content=None,
                tool_call=ToolCall(
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                ),
            )
        return LLMResponse(content=msg.content, tool_call=None)
