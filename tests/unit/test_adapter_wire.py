"""Anthropic requests through the real SDK, intercepted before network I/O."""

from __future__ import annotations

import json
import importlib
from contextlib import asynccontextmanager

import pytest

from grip.adapters.anthropic import AnthropicAdapter

anthropic = pytest.importorskip("anthropic")
httpx = importlib.import_module(
    anthropic.DefaultAsyncHttpxClient.__mro__[1].__module__.split(".")[0]
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Click",
            "parameters": {
                "type": "object",
                "properties": {"target": {"type": "string"}},
                "required": ["target"],
            },
        },
    }
]
USER = {"role": "user", "content": "Goal"}


def assistant(arguments='{"target":"Buy"}', call_id="toolu_one"):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "click", "arguments": arguments},
            }
        ],
    }


def result(call_id="toolu_one"):
    return {"role": "tool", "tool_call_id": call_id, "content": "clicked"}


def response(blocks=None, stop="end_turn"):
    return {
        "id": "msg_probe",
        "type": "message",
        "role": "assistant",
        "model": "probe",
        "content": blocks or [{"type": "text", "text": "done"}],
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


@asynccontextmanager
async def adapter_wire(responses=None):
    captured = []
    replies = list(responses or [response()])

    def intercept(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=replies.pop(0))

    adapter = AnthropicAdapter(api_key="local-test", model="probe")
    await adapter._client.close()
    adapter._client = anthropic.AsyncAnthropic(
        api_key="local-test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(intercept)),
    )
    try:
        yield adapter, captured
    finally:
        await adapter._client.close()


_VALID = [
    ([USER], [], None),
    ([{"role": "system", "content": "Rules"}, USER], TOOLS, "Rules"),
    ([{"role": "system", "content": "A"}, {"role": "system", "content": "B"}, USER], TOOLS, "A\nB"),
    ([USER, {"role": "assistant", "content": "Thinking"}, USER], [], None),
    (
        [
            USER,
            assistant('{"target":"Buy","nested":{"ok":true,"empty":null,"text":"Ω"}}'),
            result(),
        ],
        TOOLS,
        None,
    ),
    (
        [
            USER,
            assistant("{'target': 'Buy', 'nested': {'ok': True, 'empty': None, 'text': 'Ω'}}"),
            result(),
        ],
        TOOLS,
        None,
    ),
    ([USER, assistant({"target": "Buy"}), result()], TOOLS, None),
]
_INVALID = [
    ([USER, assistant("[1,2]"), result()], TOOLS),
    ([USER, assistant("not syntax"), result()], TOOLS),
    ([USER, assistant("{'target': (1, 2)}"), result()], TOOLS),
    ([USER, assistant("{1: 'bad'}"), result()], TOOLS),
    ([USER, assistant('{"x":NaN}'), result()], TOOLS),
    ([USER, result()], TOOLS),
    ([USER, assistant(), result("other")], TOOLS),
    ([USER, assistant(), result(), assistant(), result()], TOOLS),
    ([USER, assistant()], TOOLS),
    ([USER, {"role": "developer", "content": "hidden"}], TOOLS),
    ([USER, {"role": "user", "content": [{"type": "image"}]}], TOOLS),
    ([USER], [{"type": "custom", "name": "bad"}]),
    ([USER, {"role": "system", "content": "late"}], TOOLS),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("messages,tools,system", _VALID)
async def test_valid_native_serialization_fixture(messages, tools, system):
    async with adapter_wire() as (adapter, captured):
        await adapter.complete(messages, tools)
    assert len(captured) == 1
    body = captured[0]
    assert body.get("system") == system
    assert all(m["role"] in {"user", "assistant"} for m in body["messages"])
    assert all("tool_calls" not in m for m in body["messages"])
    if tools:
        assert body["tools"][0] == {
            "name": "click",
            "description": "Click",
            "input_schema": TOOLS[0]["function"]["parameters"],
        }
        assert body["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    if any(m["role"] == "tool" for m in messages):
        use = body["messages"][-2]["content"][-1]
        reply = body["messages"][-1]["content"][0]
        assert use["type"] == "tool_use" and use["id"] == reply["tool_use_id"] == "toolu_one"
        assert use["input"]["target"] == "Buy"
        assert reply == {"type": "tool_result", "tool_use_id": "toolu_one", "content": "clicked"}
        if "nested" in use["input"]:
            assert use["input"]["nested"] == {"ok": True, "empty": None, "text": "Ω"}


@pytest.mark.asyncio
@pytest.mark.parametrize("messages,tools", _INVALID)
async def test_invalid_native_serialization_fixture_fails_before_http(messages, tools):
    async with adapter_wire() as (adapter, captured):
        with pytest.raises(ValueError):
            await adapter.complete(messages, tools)
        assert captured == []


@pytest.mark.asyncio
async def test_native_two_request_tool_id_and_mixed_text_roundtrip():
    first = response(
        [
            {"type": "text", "text": "Clicking"},
            {"type": "tool_use", "id": "toolu_real", "name": "click", "input": {"target": "Buy"}},
        ],
        "tool_use",
    )
    async with adapter_wire([first, response()]) as (adapter, captured):
        reply = await adapter.complete([USER], TOOLS)
        assert reply.content == "Clicking" and reply.tool_call.id == "toolu_real"
        replay = assistant(reply.tool_call.arguments, reply.tool_call.id)
        replay["content"] = reply.content
        final = await adapter.complete([USER, replay, result(reply.tool_call.id)], TOOLS)
        assert final.content == "done" and final.tool_call is None
    assert len(captured) == 2
    assert captured[1]["messages"][1]["content"][0] == {"type": "text", "text": "Clicking"}
    assert captured[1]["messages"][1]["content"][1]["id"] == "toolu_real"
    assert captured[1]["messages"][2]["content"][0]["tool_use_id"] == "toolu_real"


@pytest.mark.asyncio
async def test_multiple_native_tool_calls_fail_explicitly():
    blocks = [
        {"type": "tool_use", "id": f"toolu_{i}", "name": "click", "input": {"target": "Buy"}}
        for i in range(2)
    ]
    async with adapter_wire([response(blocks, "tool_use")]) as (adapter, captured):
        with pytest.raises(ValueError, match="multiple"):
            await adapter.complete([USER], TOOLS)
        assert len(captured) == 1
