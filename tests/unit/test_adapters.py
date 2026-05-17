import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from grip.adapters.base import LLMAdapter, LLMResponse, ToolCall


def test_llm_response_has_expected_fields():
    resp = LLMResponse(content="hello", tool_call=None)
    assert resp.content == "hello"
    assert resp.tool_call is None


def test_tool_call_has_expected_fields():
    tc = ToolCall(name="click", arguments={"target": "button"})
    assert tc.name == "click"
    assert tc.arguments["target"] == "button"


def test_llm_adapter_is_protocol():
    assert hasattr(LLMAdapter, "complete")


@pytest.mark.asyncio
async def test_openai_adapter_calls_api():
    with patch("grip.adapters.openai.openai") as mock_openai:
        mock_client = MagicMock()
        mock_openai.AsyncOpenAI.return_value = mock_client

        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Found the item"
        mock_choice.message.tool_calls = None
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        from grip.adapters.openai import OpenAIAdapter
        adapter = OpenAIAdapter(api_key="sk-test", model="gpt-4o")
        result = await adapter.complete(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
        )
        assert isinstance(result, LLMResponse)
        assert result.content == "Found the item"


@pytest.mark.asyncio
async def test_anthropic_adapter_calls_api():
    with patch("grip.adapters.anthropic.anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        mock_response = MagicMock()
        mock_response.content = [MagicMock(type="text", text="Done")]
        mock_response.stop_reason = "end_turn"
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        from grip.adapters.anthropic import AnthropicAdapter
        adapter = AnthropicAdapter(api_key="sk-ant-test")
        result = await adapter.complete(
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
        )
        assert isinstance(result, LLMResponse)
        assert result.content == "Done"
