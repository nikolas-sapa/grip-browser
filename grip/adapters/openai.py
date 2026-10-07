from __future__ import annotations

import importlib
import json
from typing import Any

from grip.adapters.base import (
    LLMProtocolError, LLMResponse, LLMUsage, ToolCall, _reported_count, _validate_calls,
)

openai: Any
try:
    openai = importlib.import_module("openai")
except ImportError:
    openai = None


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
        kwargs: dict[str, Any] = {"model": self._model, "messages": [
            {key: value for key, value in message.items() if key != "replay_metadata"}
            for message in messages
        ]}
        if tools:
            kwargs["tools"] = tools
        response = await self._client.chat.completions.create(**kwargs)
        raw_usage = getattr(response, "usage", None)
        usage = (
            None
            if raw_usage is None
            else LLMUsage(
                provider="openai",
                total_tokens=_reported_count(getattr(raw_usage, "total_tokens", None)),
                input_tokens=_reported_count(getattr(raw_usage, "prompt_tokens", None)),
                output_tokens=_reported_count(getattr(raw_usage, "completion_tokens", None)),
                cache_read_input_tokens=_reported_count(
                    getattr(
                        getattr(raw_usage, "prompt_tokens_details", None), "cached_tokens", None
                    )
                ),
                thought_tokens=_reported_count(
                    getattr(
                        getattr(raw_usage, "completion_tokens_details", None),
                        "reasoning_tokens",
                        None,
                    )
                ),
            )
        )
        if not response.choices:
            raise LLMProtocolError("model response contains no choices", usage)
        choice = response.choices[0]
        msg = choice.message
        if msg.content is not None and not isinstance(msg.content, str):
            raise LLMProtocolError("assistant content must be text or null", usage)
        if msg.tool_calls:
            calls = []
            try:
                for tc in msg.tool_calls:
                    arguments = json.loads(tc.function.arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("not an object")
                    json.dumps(arguments, allow_nan=False)
                    calls.append(ToolCall(tc.function.name, arguments, tc.id))
            except (TypeError, ValueError, RecursionError):
                raise LLMProtocolError(
                    "tool arguments must be a valid JSON object", usage
                ) from None
            _validate_calls(tuple(calls), usage, require_ids=True)
            return LLMResponse(content=msg.content, usage=usage, tool_call=calls[0],
                               tool_calls=tuple(calls))
        return LLMResponse(content=msg.content, tool_call=None, usage=usage)
