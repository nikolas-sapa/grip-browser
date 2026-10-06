"""Provider counts use SDK response shapes; no paid calls."""

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from grip.adapters.base import LLMUsage
from grip.adapters.openai import OpenAIAdapter
from grip.adapters.anthropic import AnthropicAdapter
from grip.adapters.gemini import GeminiAdapter
from grip.trace import Trace, TraceEntry


@pytest.mark.parametrize(
    "provider,raw,expected",
    [
        ("openai", NS(prompt_tokens=12, completion_tokens=3), (12, 3, None, None, None)),
        ("openai", NS(prompt_tokens=0, completion_tokens=0), (0, 0, None, None, None)),
        (
            "openai",
            NS(
                prompt_tokens=12,
                completion_tokens=3,
                prompt_tokens_details=NS(cached_tokens=9),
                completion_tokens_details=NS(reasoning_tokens=2),
            ),
            (12, 3, 9, None, 2),
        ),
        ("openai", None, None),
        (
            "anthropic",
            NS(
                input_tokens=10,
                output_tokens=4,
                cache_read_input_tokens=30,
                cache_creation_input_tokens=20,
            ),
            (10, 4, 30, 20, None),
        ),
        (
            "anthropic",
            NS(
                input_tokens=0,
                output_tokens=0,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
            (0, 0, 0, 0, None),
        ),
        ("anthropic", None, None),
        (
            "gemini",
            NS(
                prompt_token_count=11,
                candidates_token_count=5,
                cached_content_token_count=7,
                thoughts_token_count=2,
            ),
            (11, 5, 7, None, 2),
        ),
        ("gemini", NS(prompt_token_count=0, candidates_token_count=0), (0, 0, None, None, None)),
        ("gemini", None, None),
    ],
)
async def test_ten_provider_usage_transcripts(provider, raw, expected):
    cls = {"openai": OpenAIAdapter, "anthropic": AnthropicAdapter, "gemini": GeminiAdapter}[
        provider
    ]
    adapter = object.__new__(cls)
    adapter._model = "test"
    if provider == "openai":
        response = NS(usage=raw, choices=[NS(message=NS(content="text", tool_calls=None))])
        adapter._client = NS(chat=NS(completions=NS(create=AsyncMock(return_value=response))))
    elif provider == "anthropic":
        response = NS(usage=raw, content=[NS(type="text", text="text")])
        adapter._client = NS(messages=NS(create=AsyncMock(return_value=response)))
    else:
        pytest.importorskip("google.genai")
        response = NS(usage_metadata=raw, candidates=[], function_calls=None, text="text")
        adapter._client = NS(aio=NS(models=NS(generate_content=AsyncMock(return_value=response))))
    result = await adapter.complete([{"role": "user", "content": "hello"}], [])
    if expected is None:
        assert result.usage is None
    else:
        assert result.usage == LLMUsage(provider, *expected)


def test_trace_reported_usage_survives_eviction_and_unknown():
    trace = Trace(max_actions=2)
    for usage in (LLMUsage("openai", 0, 0), None, LLMUsage("openai", 5, 2)):
        trace.add(TraceEntry(0, "model_call", {}, {}, 0, 1, model_usage=usage))
    assert trace.model_calls == 3
    assert trace.model_calls_with_usage == 2
    assert trace.model_usage_totals == {"input_tokens": 5, "output_tokens": 2}
    assert trace.actions[0].to_dict()["model_usage"] is None
    assert trace.total_tokens == 0


async def test_gemini_signed_response_fails_explicitly():
    pytest.importorskip("google.genai")
    adapter = object.__new__(GeminiAdapter)
    adapter._model = "test"
    response = NS(
        usage_metadata=NS(prompt_token_count=8, candidates_token_count=2, total_token_count=10),
        candidates=[NS(content=NS(parts=[NS(thought_signature=b"signed")]))],
    )
    adapter._client = NS(aio=NS(models=NS(generate_content=AsyncMock(return_value=response))))
    with pytest.raises(ValueError, match="thought signature replay is unsupported") as caught:
        await adapter.complete([{"role": "user", "content": "hello"}], [])
    assert caught.value.usage == LLMUsage("gemini", 8, 2, total_tokens=10)


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
async def test_native_sdk_intercepted_transport(provider):
    httpx = pytest.importorskip("httpx")
    if provider == "openai":
        sdk = pytest.importorskip("openai")
        payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "native-openai",
                                "type": "function",
                                "function": {"name": "done", "arguments": "{}"},
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
        }
        client = sdk.AsyncOpenAI(
            api_key="test",
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
            ),
        )
        adapter = object.__new__(OpenAIAdapter)
    elif provider == "anthropic":
        sdk = pytest.importorskip("anthropic")
        payload = {
            "id": "msg-test",
            "type": "message",
            "role": "assistant",
            "model": "test",
            "content": [
                {"type": "tool_use", "id": "native-anthropic", "name": "done", "input": {}}
            ],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 8, "output_tokens": 2},
        }
        client = sdk.AsyncAnthropic(
            api_key="test",
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
            ),
        )
        adapter = object.__new__(AnthropicAdapter)
    else:
        sdk = pytest.importorskip("google.genai")
        payload = {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {"functionCall": {"id": "native-gemini", "name": "done", "args": {}}}
                        ],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 8,
                "candidatesTokenCount": 2,
                "totalTokenCount": 10,
            },
        }
        client = sdk.Client(
            api_key="test",
            http_options={
                "async_client_args": {
                    "transport": httpx.MockTransport(
                        lambda request: httpx.Response(200, json=payload)
                    )
                }
            },
        )
        adapter = object.__new__(GeminiAdapter)
    adapter._client = client
    adapter._model = "test"
    try:
        result = await adapter.complete([{"role": "user", "content": "hello"}], [])
        assert result.usage == LLMUsage(
            provider, 8, 2, total_tokens=10 if provider != "anthropic" else None
        )
        assert result.tool_call.id == f"native-{provider}"
    finally:
        if provider == "gemini":
            await client.aio.aclose()
            client.close()
        else:
            await client.close()


def test_native_gemini_replay_preserves_call_and_result_ids():
    pytest.importorskip("google.genai")
    from grip.adapters.gemini import _to_contents

    _, contents = _to_contents(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "native-id", "function": {"name": "click", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "native-id", "content": "ok"},
        ]
    )
    assert contents[0].parts[0].function_call.id == "native-id"
    assert contents[1].parts[0].function_response.id == "native-id"


def test_trace_native_total_stays_exact_without_subdivision_double_count():
    trace = Trace(max_actions=1)
    for total in (0, 19, 20):
        trace.add(
            TraceEntry(
                0,
                "model_call",
                {},
                {},
                0,
                1,
                model_usage=LLMUsage(
                    "gemini",
                    10,
                    5,
                    cache_read_input_tokens=8,
                    thought_tokens=4,
                    total_tokens=total,
                ),
            )
        )
    assert trace.model_usage_totals["total_tokens"] == 39
    assert trace.model_usage_totals["thought_tokens"] == 12
    assert trace.model_calls == 3


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
async def test_multiple_calls_rejected_with_reported_usage(provider):
    from grip.adapters.base import LLMProtocolError

    cls = {"openai": OpenAIAdapter, "anthropic": AnthropicAdapter, "gemini": GeminiAdapter}[
        provider
    ]
    adapter = object.__new__(cls)
    adapter._model = "test"
    if provider == "openai":
        calls = [NS(id=f"c{i}", function=NS(name="click", arguments="{}")) for i in range(2)]
        response = NS(
            usage=NS(prompt_tokens=8, completion_tokens=2, total_tokens=10),
            choices=[NS(message=NS(content=None, tool_calls=calls))],
        )
        adapter._client = NS(chat=NS(completions=NS(create=AsyncMock(return_value=response))))
    elif provider == "anthropic":
        calls = [NS(type="tool_use", id=f"c{i}", name="click", input={}) for i in range(2)]
        response = NS(usage=NS(input_tokens=8, output_tokens=2), content=calls)
        adapter._client = NS(messages=NS(create=AsyncMock(return_value=response)))
    else:
        pytest.importorskip("google.genai")
        calls = [NS(id=f"c{i}", name="click", args={}) for i in range(2)]
        response = NS(
            usage_metadata=NS(prompt_token_count=8, candidates_token_count=2, total_token_count=10),
            candidates=[],
            function_calls=calls,
            text=None,
        )
        adapter._client = NS(aio=NS(models=NS(generate_content=AsyncMock(return_value=response))))
    with pytest.raises(LLMProtocolError, match="multiple tool calls") as caught:
        await adapter.complete([{"role": "user", "content": "hello"}], [])
    assert caught.value.usage == LLMUsage(
        provider, 8, 2, total_tokens=10 if provider != "anthropic" else None
    )


@pytest.mark.parametrize("arguments", ['{"secret-token":', "[]", '{"x": NaN}'])
async def test_openai_bad_arguments_retain_usage_without_raw_body(arguments):
    from grip.adapters.base import LLMProtocolError

    adapter = object.__new__(OpenAIAdapter)
    adapter._model = "test"
    response = NS(
        usage=NS(prompt_tokens=3, completion_tokens=0, total_tokens=3),
        choices=[
            NS(
                message=NS(
                    content=None,
                    tool_calls=[NS(id="call", function=NS(name="click", arguments=arguments))],
                )
            )
        ],
    )
    adapter._client = NS(chat=NS(completions=NS(create=AsyncMock(return_value=response))))
    with pytest.raises(LLMProtocolError) as caught:
        await adapter.complete([{"role": "user", "content": "hello"}], [])
    assert caught.value.usage == LLMUsage("openai", 3, 0, total_tokens=3)
    assert str(caught.value) == "tool arguments must be a valid JSON object"
    assert caught.value.__suppress_context__
