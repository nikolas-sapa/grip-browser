from __future__ import annotations

import os
from typing import Any


def adapter_from_env() -> Any | None:
    """Picks an LLMAdapter from env vars, in the same precedence order
    cli.py:_llm_adapter_or_exit and mcp/server.py:_llm_adapter_from_env each
    hand-roll today: ANTHROPIC_API_KEY, then OPENAI_API_KEY (OPENAI_BASE_URL
    routes that same key to any OpenAI-compatible endpoint), then
    GEMINI_API_KEY. Returns None if no key is set — callers decide whether
    that's fatal.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        from grip.adapters.anthropic import AnthropicAdapter

        return AnthropicAdapter()
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_BASE_URL"):
        from grip.adapters.openai import OpenAIAdapter

        return OpenAIAdapter(base_url=os.environ.get("OPENAI_BASE_URL"))
    if os.environ.get("GEMINI_API_KEY"):
        from grip.adapters.gemini import GeminiAdapter

        return GeminiAdapter()
    return None
