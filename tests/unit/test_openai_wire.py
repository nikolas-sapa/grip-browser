"""Runner history through the actual OpenAI SDK, with no network requests."""
from __future__ import annotations

import json

import pytest

from grip.adapters.openai import OpenAIAdapter
from grip.compression.summarizer import PageSnapshot
from grip.runner import Runner
from grip.trace import Trace

openai = pytest.importorskip("openai")
httpx = pytest.importorskip("httpx")


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
async def test_runner_json_history_reaches_native_openai_second_request():
    arguments = {"target": 'Buy "Ω"', "nested": {"enabled": True, "missing": None,
                 "items": [1, "two", {"off": False}]}}
    captured = []

    def intercept(request):
        captured.append(json.loads(request.content))
        if len(captured) == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [{
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
        })

    adapter = OpenAIAdapter(api_key="local-test", model="probe")
    await adapter._client.close()
    adapter._client = openai.AsyncOpenAI(
        api_key="local-test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(intercept)),
    )
    page = _Page()
    try:
        await Runner(llm=adapter, page=page, trace=Trace()).run("click Buy")
    finally:
        await adapter._client.close()
    assert len(captured) == 2 and page.clicks == [arguments["target"]]
    replay = captured[1]["messages"][-2]["tool_calls"][0]
    result = captured[1]["messages"][-1]
    assert json.loads(replay["function"]["arguments"]) == arguments
    assert replay["function"]["name"] == "click"
    assert replay["id"] == result["tool_call_id"]
    assert result["role"] == "tool" and "<page_state>" in result["content"]
