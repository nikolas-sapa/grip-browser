"""Gemini replay through the real SDK, with no network or paid requests."""
import copy
import json

import pytest

from grip.adapters.gemini import GeminiAdapter, _to_contents

sdk = pytest.importorskip("google.genai")
httpx = pytest.importorskip("httpx")


def content(index, signature="c2lnbmVk"):
    return {"role": "model", "parts": [
        {"text": f"checking {index}", "thoughtSignature": signature},
        {"functionCall": {"id": f"call-{index}", "name": "snapshot", "args": {}},
         "thoughtSignature": "Y2FsbC1zaWduYXR1cmU="},
    ]}


def history_item(response):
    call = response.tool_call
    return {"role": "assistant", "content": response.content,
            "replay_metadata": response.replay_metadata,
            "tool_calls": [{"id": call.id, "type": "function",
                            "function": {"name": call.name,
                                         "arguments": json.dumps(call.arguments)}}]}


async def test_three_native_requests_preserve_all_parts_and_signatures():
    captured = []

    def intercept(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"candidates": [
            {"content": content(len(captured)), "finishReason": "STOP"}
        ]})

    client = sdk.Client(api_key="local-test", http_options={"async_client_args": {
        "transport": httpx.MockTransport(intercept)}})
    adapter = object.__new__(GeminiAdapter)
    adapter._client, adapter._model = client, "probe"
    messages = [{"role": "user", "content": "Goal"}]
    try:
        for _ in range(3):
            response = await adapter.complete(messages, [])
            messages.extend([history_item(response), {"role": "tool",
                "tool_call_id": response.tool_call.id, "content": "snapshot result"}])
    finally:
        await client.aio.aclose()
        client.close()
    assert len(captured) == 3
    assert captured[1]["contents"][1] == content(1)
    assert captured[2]["contents"][1] == content(1)
    assert captured[2]["contents"][3] == content(2)
    assert captured[2]["contents"][2]["parts"][0]["functionResponse"]["id"] == "call-1"


def test_two_histories_keep_native_parts_isolated():
    from google.genai.types import Content
    from grip.adapters.base import LLMResponse, ToolCall
    histories = []
    for index, signature in ((1, "b25l"), (2, "dHdv")):
        native = Content.model_validate(content(index, signature))
        response = LLMResponse(None, ToolCall("snapshot", {}, f"call-{index}"),
            replay_metadata={"provider": "gemini", "content": native.model_dump(
                mode="json", exclude_none=True)})
        histories.append([history_item(response)])
    for index, signature in enumerate((b"one", b"two")):
        _, replay = _to_contents(histories[index])
        assert replay[0].parts[0].thought_signature == signature
        assert replay[0].parts[1].function_call.id == f"call-{index + 1}"


@pytest.mark.parametrize("invalid", ["bad", {"provider": "openai"},
    {"provider": "gemini", "content": "bad"},
    {"provider": "gemini", "content": {"role": "user", "parts": []}}])
async def test_invalid_metadata_fails_before_any_transport(invalid):
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    adapter = object.__new__(GeminiAdapter)
    generate = AsyncMock()
    adapter._model = "probe"
    adapter._client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(
        generate_content=generate)))
    with pytest.raises(ValueError):
        await adapter.complete([{"role": "assistant", "replay_metadata": invalid,
                                 "tool_calls": []}], [])
    generate.assert_not_awaited()


@pytest.mark.parametrize("arguments", ["[]", "broken", '{"x":NaN}', {1: "bad"},
    {"nested": (1, 2)}, None])
def test_invalid_unsigned_arguments_fail_closed(arguments):
    with pytest.raises(ValueError):
        _to_contents([{"role": "assistant", "tool_calls": [{"id": "one",
            "function": {"name": "snapshot", "arguments": arguments}}]}])


def test_unsigned_history_retains_text_and_transitional_arguments():
    _, replay = _to_contents([{"role": "assistant", "content": "Checking", "tool_calls": [
        {"id": "one", "function": {"name": "click", "arguments": "{'target': 'Buy'}"}}]}])
    assert replay[0].parts[0].text == "Checking"
    assert replay[0].parts[1].function_call.args == {"target": "Buy"}


def test_native_metadata_must_match_history_arguments():
    from google.genai.types import Content
    native = Content.model_validate(content(1)).model_dump(mode="json", exclude_none=True)
    message = {"role": "assistant", "replay_metadata": {"provider": "gemini", "content": native},
        "tool_calls": [{"id": "call-1", "function": {"name": "snapshot", "arguments": "{}"}}]}
    for change in ({"id": "wrong"}, {"function": {"name": "click", "arguments": "{}"}},
                   {"function": {"name": "snapshot", "arguments": '{"x":1}'}}):
        altered = copy.deepcopy(message)
        altered["tool_calls"][0].update(change)
        with pytest.raises(ValueError):
            _to_contents([altered])


async def test_runner_native_three_turn_wire_replay_and_private_trace(tmp_path):
    from grip.runner import Runner
    from grip.trace import Trace
    from tests.unit.test_runner import FakePage

    captured = []

    def intercept(request):
        captured.append(json.loads(request.content))
        index = len(captured)
        native = content(index) if index < 3 else {
            "role": "model", "parts": [{"text": "finished"}],
        }
        return httpx.Response(200, json={
            "candidates": [{"content": native, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 2,
                              "thoughtsTokenCount": 1, "totalTokenCount": 11},
        })

    client = sdk.Client(api_key="local-test", http_options={"async_client_args": {
        "transport": httpx.MockTransport(intercept)}})
    adapter = object.__new__(GeminiAdapter)
    adapter._client, adapter._model = client, "probe"
    trace = Trace()
    try:
        result = await Runner(adapter, FakePage(["page"]), trace).run("answer")
    finally:
        await client.aio.aclose()
        client.close()
    assert len(captured) == result.model_calls == trace.model_calls == 3
    assert result.outcome == "model_text" and result.tokens == 33 and result.usage_complete
    assert result.usage == {"input_tokens": 24, "output_tokens": 6,
                            "thought_tokens": 3, "total_tokens": 33}
    assert sum(entry.action == "snapshot" for entry in trace.actions) == 2
    assert captured[1]["contents"][1] == content(1)
    assert captured[2]["contents"][1] == content(1)
    assert captured[2]["contents"][3] == content(2)
    for position, index in ((2, 1), (4, 2)):
        function_response = captured[2]["contents"][position]["parts"][0]["functionResponse"]
        assert function_response["id"] == f"call-{index}"
        assert function_response["name"] == "snapshot"
    path = tmp_path / "native-trace.jsonl"
    trace.to_jsonl(str(path))
    trace_text = path.read_text()
    assert "c2lnbmVk" not in trace_text and "Y2FsbC1zaWduYXR1cmU=" not in trace_text
    assert "thought_signature" not in trace_text and "replay_metadata" not in trace_text


async def test_runner_signed_native_call_without_id_keeps_wire_id_absent():
    from grip.runner import Runner
    from grip.trace import Trace
    from tests.unit.test_runner import FakePage

    native = content(1)
    del native["parts"][1]["functionCall"]["id"]
    captured = []

    def intercept(request):
        captured.append(json.loads(request.content))
        reply = native if len(captured) == 1 else {
            "role": "model", "parts": [{"text": "finished"}],
        }
        return httpx.Response(200, json={"candidates": [
            {"content": reply, "finishReason": "STOP"},
        ]})

    client = sdk.Client(api_key="local-test", http_options={"async_client_args": {
        "transport": httpx.MockTransport(intercept)}})
    adapter = object.__new__(GeminiAdapter)
    adapter._client, adapter._model = client, "probe"
    trace = Trace()
    runner = Runner(adapter, FakePage(["page"]), trace)
    try:
        result = await runner.run("answer")
    finally:
        await client.aio.aclose()
        client.close()
    assert len(captured) == result.model_calls == 2
    assert sum(entry.action == "snapshot" for entry in trace.actions) == 1
    assert captured[1]["contents"][1] == native
    wire_result = captured[1]["contents"][2]["parts"][0]["functionResponse"]
    assert wire_result["name"] == "snapshot" and "id" not in wire_result
    assistant = next(message for message in runner._messages if message["role"] == "assistant")
    assert assistant["tool_calls"][0]["id"] == "grip_call_0"
