"""Runner history through the actual OpenAI SDK, with no network requests."""
from __future__ import annotations

import json
import importlib

import pytest

from grip.adapters.openai import OpenAIAdapter
from grip.adapters.base import LLMProtocolError, LLMUsage
from grip.compression.summarizer import PageSnapshot
from grip.runner import Runner
from grip.trace import Trace

openai = pytest.importorskip("openai")
httpx = importlib.import_module(
    openai.DefaultAsyncHttpxClient.__mro__[1].__module__.split(".")[0]
)


class _Page:
    def __init__(self):
        self.clicks = []

    async def snapshot(self):
        return PageSnapshot(1, "https://fixture.test", "Fixture", [], "Buy", 0)

    async def click(self, target):
        self.clicks.append(target)

    def payload(self, last_sent_version):
        return "PAGE: Fixture", 1

    def consume_dialogs(self):
        return []


@pytest.mark.asyncio
@pytest.mark.parametrize("assistant_text", [None, "Checking before clicking."])
async def test_runner_json_history_reaches_native_openai_second_request(assistant_text):
    arguments = {"target": 'Buy "Ω"', "nested": {"enabled": True, "missing": None,
                 "items": [1, "two", {"off": False}]}}
    captured = []

    def intercept(request):
        captured.append(json.loads(request.content))
        if len(captured) == 1:
            message = {"role": "assistant", "content": assistant_text, "tool_calls": [{
                "id": "call_native", "type": "function", "function": {
                    "name": "click", "arguments": json.dumps(arguments),
                },
            }]}
            finish = "tool_calls"
        else:
            message = {"role": "assistant", "content": "finished"}
            finish = "stop"
        return httpx.Response(200, json={
            "id": "chatcmpl_probe", "object": "chat.completion", "created": 0,
            "model": "probe", "choices": [{"index": 0, "message": message,
                                             "finish_reason": finish}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
        })

    adapter = OpenAIAdapter(api_key="local-test", model="probe")
    await adapter._client.close()
    adapter._client = openai.AsyncOpenAI(
        api_key="local-test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(intercept)),
    )
    page = _Page()
    try:
        run_result = await Runner(llm=adapter, page=page, trace=Trace()).run("click Buy")
    finally:
        await adapter._client.close()
    assert len(captured) == 2 and page.clicks == [arguments["target"]]
    assert run_result.model_calls == 2 and run_result.tokens == 20
    assert run_result.usage_complete
    assert all(body["parallel_tool_calls"] is False for body in captured)
    assert captured[1]["messages"][-2]["content"] == assistant_text
    replay = captured[1]["messages"][-2]["tool_calls"][0]
    result = captured[1]["messages"][-1]
    assert json.loads(replay["function"]["arguments"]) == arguments
    assert replay["function"]["name"] == "click"
    assert replay["id"] == result["tool_call_id"]
    assert result["role"] == "tool" and "<page_state>" in result["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("multiple_calls", [False, True])
async def test_native_openai_without_tools_omits_parallel_flag(multiple_calls):
    captured = []

    def intercept(request):
        captured.append(json.loads(request.content))
        message = {"role": "assistant", "content": "finished"}
        if multiple_calls:
            message["tool_calls"] = [
                {"id": f"call_{i}", "type": "function", "function": {
                    "name": "click", "arguments": '{"target":"Buy"}',
                }}
                for i in range(2)
            ]
        return httpx.Response(200, json={
            "id": "chatcmpl_probe", "object": "chat.completion", "created": 0,
            "model": "probe", "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if multiple_calls else "stop"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
        })

    adapter = OpenAIAdapter(api_key="local-test", model="probe")
    await adapter._client.close()
    adapter._client = openai.AsyncOpenAI(
        api_key="local-test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(intercept)),
    )
    try:
        if multiple_calls:
            with pytest.raises(LLMProtocolError, match="multiple tool calls") as caught:
                await adapter.complete([{"role": "user", "content": "hello"}], [])
            assert caught.value.usage == LLMUsage("openai", 8, 2, total_tokens=10)
        else:
            response = await adapter.complete([{"role": "user", "content": "hello"}], [])
            assert response.content == "finished" and response.tool_call is None
    finally:
        await adapter._client.close()
    assert len(captured) == 1
    assert "tools" not in captured[0]
    assert "parallel_tool_calls" not in captured[0]
