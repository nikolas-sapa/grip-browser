from __future__ import annotations

try:
    import anthropic as anthropic
except ImportError:
    anthropic = None

from grip.adapters.base import LLMResponse, ToolCall


class AnthropicAdapter:
    def __init__(
        self, api_key: str | None = None, model: str = "claude-opus-4-7"
    ) -> None:
        if anthropic is None:
            raise ImportError("pip install grip-browser[anthropic]")
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        kwargs = {"model": self._model, "max_tokens": 4096, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        response = await self._client.messages.create(**kwargs)
        if response.stop_reason == "tool_use":
            for block in response.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    return LLMResponse(
                        content=None,
                        tool_call=ToolCall(name=block.name, arguments=block.input),
                    )
        text = "".join(block.text for block in response.content if hasattr(block, "text"))
        return LLMResponse(content=text, tool_call=None)
