from __future__ import annotations

import json
from typing import Any

try:
    import openai  # type: ignore[import-not-found]  # optional dependency, guarded below
except ImportError:
    openai = None

from grip.adapters.base import LLMResponse, ToolCall


class OpenAIAdapter:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o",
        base_url: str | None = None,
    ) -> None:
        """base_url points this at any OpenAI-compatible endpoint (Ollama,
        vLLM, LM Studio, OpenRouter, Together, Groq, ...). Most local servers
        don't check the key, but the SDK still requires a non-empty string —
        default to a placeholder only when base_url is set, so plain OpenAI
        usage still fails loudly on a missing key.
        """
        if openai is None:
            raise ImportError("pip install grip-browser[openai]")
        if base_url is not None and api_key is None:
            api_key = "not-needed"
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
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
