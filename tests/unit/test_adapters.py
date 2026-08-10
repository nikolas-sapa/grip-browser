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


@pytest.mark.asyncio
async def test_openai_adapter_base_url_routes_to_compatible_endpoint():
    """base_url is how Ollama/vLLM/LM Studio/OpenRouter/Together/Groq get
    used: same wire format, different host, no new adapter class."""
    with patch("grip.adapters.openai.openai") as mock_openai:
        mock_client = MagicMock()
        mock_openai.AsyncOpenAI.return_value = mock_client

        from grip.adapters.openai import OpenAIAdapter
        OpenAIAdapter(model="llama3", base_url="http://localhost:11434/v1")

        mock_openai.AsyncOpenAI.assert_called_once_with(
            api_key="not-needed", base_url="http://localhost:11434/v1"
        )


@pytest.mark.asyncio
async def test_openai_adapter_base_url_keeps_explicit_api_key():
    with patch("grip.adapters.openai.openai") as mock_openai:
        mock_openai.AsyncOpenAI.return_value = MagicMock()

        from grip.adapters.openai import OpenAIAdapter
        OpenAIAdapter(api_key="sk-real", base_url="https://openrouter.ai/api/v1")

        mock_openai.AsyncOpenAI.assert_called_once_with(
            api_key="sk-real", base_url="https://openrouter.ai/api/v1"
        )


def _mock_genai_types():
    """A stand-in for google.genai.types that records what each constructor
    was called with instead of building real pydantic models, so assertions
    can inspect the actual request shape without the package installed.
    """
    mock_types = MagicMock()
    mock_types.Part.from_text.side_effect = lambda text: {"text": text}
    mock_types.Part.from_function_call.side_effect = (
        lambda name, args: {"function_call": {"name": name, "args": args}}
    )
    mock_types.Part.from_function_response.side_effect = (
        lambda name, response: {"function_response": {"name": name, "response": response}}
    )
    mock_types.Content.side_effect = lambda role, parts: {"role": role, "parts": parts}
    mock_types.GenerateContentConfig.side_effect = lambda **kw: kw
    mock_types.FunctionDeclaration.side_effect = lambda **kw: kw
    mock_types.Tool.side_effect = lambda **kw: kw
    return mock_types


_TOOLS = [
    {"type": "function", "function": {
        "name": "click",
        "description": "Click an element.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string"}
        }, "required": ["target"]},
    }},
    {"type": "function", "function": {
        "name": "snapshot",
        "description": "Take a snapshot.",
        "parameters": {"type": "object", "properties": {}},
    }},
]


@pytest.mark.asyncio
async def test_gemini_adapter_encodes_request_from_runner_message_shapes():
    """Feeds the exact message shapes runner.py emits — including the
    str(dict) repr (not JSON) that runner.py:214 writes into a replayed
    assistant tool_call's arguments field — and checks the encoded request,
    not just that a response comes back.
    """
    mock_types = _mock_genai_types()
    with patch("grip.adapters.gemini.genai") as mock_genai, \
         patch("grip.adapters.gemini.genai_types", mock_types):
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.function_calls = None
        mock_response.text = "done"
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        from grip.adapters.gemini import GeminiAdapter
        adapter = GeminiAdapter(api_key="test-key")

        messages = [
            {"role": "system", "content": "You are a browser agent."},
            {"role": "user", "content": "Goal: find the price"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "0", "type": "function", "function": {
                    "name": "click",
                    # str(dict), single-quoted — exactly what runner.py writes.
                    "arguments": str({"target": "buy button"}),
                }}],
            },
            {"role": "tool", "tool_call_id": "0", "content": "clicked"},
        ]
        await adapter.complete(messages=messages, tools=_TOOLS)

        call_kwargs = mock_client.aio.models.generate_content.call_args.kwargs
        assert call_kwargs["model"] == "gemini-2.0-flash"
        config = call_kwargs["config"]
        assert config["system_instruction"] == "You are a browser agent."

        contents = call_kwargs["contents"]
        assert contents[0] == {"role": "user", "parts": [{"text": "Goal: find the price"}]}
        assert contents[1] == {
            "role": "model",
            "parts": [{"function_call": {"name": "click", "args": {"target": "buy button"}}}],
        }
        assert contents[2] == {
            "role": "user",
            "parts": [{"function_response": {"name": "click", "response": {"result": "clicked"}}}],
        }

        # Tool declarations: "click" keeps its schema, "snapshot" (empty
        # properties) omits parameters_json_schema rather than sending {}.
        tools_arg = config["tools"]
        declarations = tools_arg[0]["function_declarations"]
        assert declarations[0]["name"] == "click"
        assert "parameters_json_schema" in declarations[0]
        assert declarations[1]["name"] == "snapshot"
        assert "parameters_json_schema" not in declarations[1]


@pytest.mark.asyncio
async def test_gemini_adapter_decodes_function_call_response():
    mock_types = _mock_genai_types()
    with patch("grip.adapters.gemini.genai") as mock_genai, \
         patch("grip.adapters.gemini.genai_types", mock_types):
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        mock_call = MagicMock()
        mock_call.name = "click"
        mock_call.args = {"target": "submit"}
        mock_response = MagicMock()
        mock_response.function_calls = [mock_call]
        mock_response.text = None
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        from grip.adapters.gemini import GeminiAdapter
        adapter = GeminiAdapter(api_key="test-key")
        result = await adapter.complete(
            messages=[{"role": "user", "content": "hello"}], tools=_TOOLS
        )

        assert result.content is None
        assert result.tool_call == ToolCall(name="click", arguments={"target": "submit"})


@pytest.mark.asyncio
async def test_gemini_adapter_decodes_text_response():
    mock_types = _mock_genai_types()
    with patch("grip.adapters.gemini.genai") as mock_genai, \
         patch("grip.adapters.gemini.genai_types", mock_types):
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.function_calls = None
        mock_response.text = "Found the item"
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        from grip.adapters.gemini import GeminiAdapter
        adapter = GeminiAdapter(api_key="test-key")
        result = await adapter.complete(
            messages=[{"role": "user", "content": "hello"}], tools=[]
        )

        assert result.content == "Found the item"
        assert result.tool_call is None


def test_adapter_from_env_precedence(monkeypatch):
    from grip.adapters import adapter_from_env

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert adapter_from_env() is None

    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    with patch("grip.adapters.gemini.genai") as mock_genai:
        mock_genai.Client.return_value = MagicMock()
        adapter = adapter_from_env()
        from grip.adapters.gemini import GeminiAdapter
        assert isinstance(adapter, GeminiAdapter)

    # ANTHROPIC_API_KEY outranks both OPENAI_API_KEY and GEMINI_API_KEY,
    # matching cli.py:_llm_adapter_or_exit's existing precedence.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with patch("grip.adapters.anthropic.anthropic") as mock_anthropic:
        mock_anthropic.AsyncAnthropic.return_value = MagicMock()
        adapter = adapter_from_env()
        from grip.adapters.anthropic import AnthropicAdapter
        assert isinstance(adapter, AnthropicAdapter)
