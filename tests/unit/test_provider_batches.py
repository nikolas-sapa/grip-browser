"""Native provider batches, intercepted before network I/O."""
import json
import importlib

import pytest

from grip.adapters.base import LLMProtocolError, LLMResponse, ToolCall, validate_replay_metadata


def test_response_batch_preserves_legacy_constructor_and_normalizes_sequence():
    first, second = ToolCall("snapshot", {}, "one"), ToolCall("read", {}, "two")
    legacy = LLMResponse("text", first, None, None)
    assert legacy.tool_calls == (first,) and legacy.tool_call is first
    plural = LLMResponse("text", None, tool_calls=[first, second])
    assert plural.tool_calls == (first, second) and plural.tool_call is first
    with pytest.raises(ValueError, match="first batch call"):
        LLMResponse(None, second, tool_calls=(first, second))


def _native(provider, offset, count, invalid=False):
    calls = [{"id": f"call-{i}", "name": "snapshot",
              "args": {"number": i, "enabled": True, "missing": None, "text": "Ω"}}
             for i in range(offset, offset + count)]
    if invalid:
        calls[-1]["args"] = {"bad": float("nan")}
    if provider == "openai":
        message = {"role": "assistant", "content": "before" if count else "finished"}
        if count:
            message["tool_calls"] = [{"id": c["id"], "type": "function", "function": {
                "name": c["name"], "arguments": json.dumps(c["args"]),
            }} for c in calls]
        return {"id": "chatcmpl-probe", "object": "chat.completion", "created": 0,
            "model": "probe", "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if count else "stop"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10}}
    parts = [{"type": "text", "text": "before" if count else "finished"}]
    for call in calls:
        parts += [{"type": "tool_use", "id": call["id"], "name": call["name"],
                   "input": call["args"]}, {"type": "text", "text": "between"}]
    if provider == "anthropic":
        return {"id": "msg-probe", "type": "message", "role": "assistant", "model": "probe",
            "content": parts, "stop_reason": "tool_use" if count else "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 8, "output_tokens": 2,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}
    native = {"role": "model", "parts": [
        {"text": "before" if count else "finished", "thoughtSignature": "c2lnbmVk"},
    ]}
    for call in calls:
        native["parts"] += [{"functionCall": call, "thoughtSignature": "Y2FsbA=="},
                             {"text": "between", "thoughtSignature": "dGV4dA=="}]
    return {"candidates": [{"content": native, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 2,
                          "thoughtsTokenCount": 0, "totalTokenCount": 10}}


def _http(provider):
    if provider == "gemini":
        return pytest.importorskip("httpx")
    sdk = pytest.importorskip(provider)
    return importlib.import_module(sdk.DefaultAsyncHttpxClient.__mro__[1].__module__.split(".")[0])


async def _client(provider, intercept):
    httpx = _http(provider)
    if provider == "gemini":
        sdk = pytest.importorskip("google.genai")
        from grip.adapters.gemini import GeminiAdapter
        client = sdk.Client(api_key="local-test", http_options={"async_client_args": {
            "transport": httpx.MockTransport(intercept)}})
        adapter = object.__new__(GeminiAdapter)
    else:
        sdk = pytest.importorskip(provider)
        if provider == "openai":
            from grip.adapters.openai import OpenAIAdapter
            client_class, adapter_class = sdk.AsyncOpenAI, OpenAIAdapter
        else:
            from grip.adapters.anthropic import AnthropicAdapter
            client_class, adapter_class = sdk.AsyncAnthropic, AnthropicAdapter
        client = client_class(api_key="local-test",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(intercept)))
        adapter = object.__new__(adapter_class)
    adapter._client, adapter._model = client, "probe"
    return adapter


async def _close(adapter, provider):
    if provider == "gemini":
        await adapter._client.aio.aclose()
        adapter._client.close()
    else:
        await adapter._client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
async def test_native_three_turn_five_call_batch_history(provider):
    httpx = _http(provider)
    captured = []
    replies = [_native(provider, 0, 2), _native(provider, 2, 3), _native(provider, 5, 0)]

    def intercept(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=replies[len(captured) - 1])

    adapter = await _client(provider, intercept)
    messages = [{"role": "user", "content": "Goal"}]
    calls, responses = [], []
    try:
        for _ in range(3):
            response = await adapter.complete(messages, [])
            responses.append(response)
            validate_replay_metadata(response)
            if not response.tool_calls:
                continue
            calls.extend(response.tool_calls)
            assistant = {"role": "assistant", "content": response.content, "tool_calls": [
                {"id": c.id, "type": "function", "function": {
                    "name": c.name, "arguments": json.dumps(c.arguments),
                }} for c in response.tool_calls]}
            if response.replay_metadata is not None:
                assistant["replay_metadata"] = response.replay_metadata
            messages.append(assistant)
            messages.extend({"role": "tool", "tool_call_id": c.id,
                             "content": f"result-{c.id}"} for c in response.tool_calls)
    finally:
        await _close(adapter, provider)
    assert len(captured) == 3 and len(calls) == 5
    assert [c.id for c in calls] == [f"call-{i}" for i in range(5)]
    assert [c.arguments["number"] for c in calls] == list(range(5))
    assert all(c.arguments["enabled"] is True and c.arguments["missing"] is None for c in calls)
    assert responses[-1].content == "finished"
    assert sum(r.usage.input_tokens + r.usage.output_tokens for r in responses) == 30
    for request in captured:
        assert "parallel_tool_calls" not in request
        assert "disable_parallel_tool_use" not in request.get("tool_choice", {})
    if provider == "openai":
        assert captured[2]["messages"][1]["content"] == "before"
        assert len(captured[2]["messages"][1]["tool_calls"]) == 2
        assert len(captured[2]["messages"][4]["tool_calls"]) == 3
        assert [m["tool_call_id"] for m in captured[2]["messages"] if m["role"] == "tool"] == [
            f"call-{i}" for i in range(5)]
    elif provider == "anthropic":
        assert captured[2]["messages"][1]["content"] == replies[0]["content"]
        assert captured[2]["messages"][3]["content"] == replies[1]["content"]
        assert [len(captured[2]["messages"][i]["content"]) for i in (2, 4)] == [2, 3]
        assert [p["tool_use_id"] for i in (2, 4)
                for p in captured[2]["messages"][i]["content"]] == [f"call-{i}" for i in range(5)]
    else:
        assert captured[2]["contents"][1] == replies[0]["candidates"][0]["content"]
        assert captured[2]["contents"][3] == replies[1]["candidates"][0]["content"]
        assert [len(captured[2]["contents"][i]["parts"]) for i in (2, 4)] == [2, 3]
        assert [p["functionResponse"]["id"] for i in (2, 4)
                for p in captured[2]["contents"][i]["parts"]] == [f"call-{i}" for i in range(5)]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
async def test_invalid_second_native_call_retains_reported_usage(provider):
    httpx = _http(provider)
    adapter = await _client(provider, lambda request: httpx.Response(
        200, content=json.dumps(_native(provider, 0, 2, invalid=True)),
        headers={"content-type": "application/json"}))
    try:
        with pytest.raises(LLMProtocolError) as caught:
            await adapter.complete([{"role": "user", "content": "Goal"}], [])
        assert caught.value.usage.input_tokens == 8
        assert caught.value.usage.output_tokens == 2
    finally:
        await _close(adapter, provider)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
async def test_duplicate_second_native_id_retains_reported_usage(provider):
    httpx = _http(provider)
    payload = _native(provider, 0, 2)
    if provider == "openai":
        payload["choices"][0]["message"]["tool_calls"][1]["id"] = "call-0"
    elif provider == "anthropic":
        payload["content"][3]["id"] = "call-0"
    else:
        payload["candidates"][0]["content"]["parts"][3]["functionCall"]["id"] = "call-0"
    adapter = await _client(provider, lambda request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(LLMProtocolError, match="duplicate") as caught:
            await adapter.complete([{"role": "user", "content": "Goal"}], [])
        assert caught.value.usage.input_tokens == 8
        assert caught.value.usage.output_tokens == 2
    finally:
        await _close(adapter, provider)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["anthropic", "gemini"])
@pytest.mark.parametrize("defect", ["missing", "reordered", "duplicate", "interrupted"])
async def test_invalid_batch_result_history_fails_before_native_transport(provider, defect):
    captured = []
    httpx = _http(provider)

    def intercept(request):
        captured.append(request)
        return httpx.Response(200, json=_native(provider, 0, 0))

    adapter = await _client(provider, intercept)
    history = [{"role": "user", "content": "Goal"}, {
        "role": "assistant", "content": "checking", "tool_calls": [
            {"id": f"call-{i}", "type": "function", "function": {
                "name": "snapshot", "arguments": "{}"}} for i in range(2)]},
        {"role": "tool", "tool_call_id": "call-0", "content": "first"},
        {"role": "tool", "tool_call_id": "call-1", "content": "second"}]
    if defect == "missing":
        history.pop()
    elif defect == "reordered":
        history[-2:] = reversed(history[-2:])
    elif defect == "duplicate":
        history[-1]["tool_call_id"] = "call-0"
    else:
        history.insert(-1, {"role": "user", "content": "interrupted"})
    try:
        with pytest.raises(ValueError):
            await adapter.complete(history, [])
        assert captured == []
    finally:
        await _close(adapter, provider)


@pytest.mark.parametrize("provider", ["anthropic", "gemini"])
@pytest.mark.parametrize("defect", ["order", "id", "arguments", "tuple", "count"])
def test_shared_replay_metadata_rejects_mismatched_batch(provider, defect):
    from grip.adapters.base import LLMUsage
    calls = (ToolCall("snapshot", {"x": [1]}, "first"),
             ToolCall("read", {}, "second"))
    if provider == "anthropic":
        native = [{"type": "tool_use", "name": c.name, "id": c.id, "input": c.arguments}
                  for c in calls]
        argument_key = "input"
    else:
        native = [{"name": c.name, "id": c.id, "args": c.arguments} for c in calls]
        argument_key = "args"
    if defect == "order":
        native.reverse()
    elif defect == "id":
        native[1]["id"] = "bad"
    elif defect == "arguments":
        native[0][argument_key] = {"x": [True]}
    elif defect == "tuple":
        native[0][argument_key] = {"x": (1,)}
    else:
        native.pop()
    content = native if provider == "anthropic" else {
        "role": "model", "parts": [{"function_call": call} for call in native]}
    usage = LLMUsage(provider, 8, 2)
    response = LLMResponse(None, calls[0], usage,
        {"provider": provider, "content": content}, calls)
    with pytest.raises(LLMProtocolError) as caught:
        validate_replay_metadata(response)
    assert caught.value.usage is usage


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "anthropic"])
async def test_missing_second_required_native_id_retains_usage(provider):
    httpx = _http(provider)
    payload = _native(provider, 0, 2)
    if provider == "openai":
        payload["choices"][0]["message"]["tool_calls"][1]["id"] = None
    else:
        payload["content"][3]["id"] = None
    adapter = await _client(provider, lambda request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(LLMProtocolError) as caught:
            await adapter.complete([{"role": "user", "content": "Goal"}], [])
        assert caught.value.usage.input_tokens == 8
    finally:
        await _close(adapter, provider)


@pytest.mark.asyncio
async def test_gemini_batch_missing_native_ids_stay_absent_on_wire():
    provider = "gemini"
    httpx = _http(provider)
    payload = _native(provider, 0, 2)
    for part in payload["candidates"][0]["content"]["parts"]:
        if "functionCall" in part:
            del part["functionCall"]["id"]
    captured = []

    def intercept(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=payload if len(captured) == 1 else _native(provider, 0, 0))

    adapter = await _client(provider, intercept)
    try:
        reply = await adapter.complete([{"role": "user", "content": "Goal"}], [])
        assert len(reply.tool_calls) == 2 and all(call.id is None for call in reply.tool_calls)
        history = [{"role": "user", "content": "Goal"}, {
            "role": "assistant", "content": reply.content, "replay_metadata": reply.replay_metadata,
            "tool_calls": [{"id": f"synthetic-{i}", "type": "function", "function": {
                "name": call.name, "arguments": json.dumps(call.arguments)}}
                for i, call in enumerate(reply.tool_calls)]},
            {"role": "tool", "tool_call_id": "synthetic-0", "content": "first"},
            {"role": "tool", "tool_call_id": "synthetic-1", "content": "second"}]
        await adapter.complete(history, [])
    finally:
        await _close(adapter, provider)
    assert captured[1]["contents"][1] == payload["candidates"][0]["content"]
    assert len(captured[1]["contents"][2]["parts"]) == 2
    assert all("id" not in part["functionResponse"] for part in captured[1]["contents"][2]["parts"])


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,invalid", [
    ("gemini", {"text": {}}),
    ("gemini", {"unknown_part": "ignored"}),
    ("gemini", {"text": "visible", "thoughtSignature": {}}),
    ("gemini", {"text": "visible", "thoughtSignature": "not base64"}),
    ("gemini", {"text": "visible", "thought": "true"}),
    ("gemini", {"function_call": {"name": "click", "args": {"target": "Menu"}, "id": "one"},
                "functionCall": {"name": "click", "args": {"target": "Other"}, "id": "one"}}),
    ("anthropic", {"type": "text", "text": {}}),
    ("anthropic", {"type": "unknown", "text": "ignored"}),
    ("anthropic", {"type": "thinking", "thinking": "private", "signature": {}}),
    ("anthropic", {"type": "redacted_thinking", "data": {}}),
])
async def test_malformed_native_part_blocks_runner_before_any_action(provider, invalid):
    from grip.adapters.base import LLMUsage
    from grip.runner import Runner
    from grip.trace import Trace
    from tests.unit.test_runner import FakePage, make_llm
    from unittest.mock import AsyncMock

    call = ToolCall("click", {"target": "Menu"}, "one")
    if provider == "gemini":
        native = {"role": "model", "parts": [{"function_call": {
            "name": call.name, "args": call.arguments, "id": call.id}}, invalid]}
    else:
        native = [{"type": "tool_use", "name": call.name,
                   "input": call.arguments, "id": call.id}, invalid]
    usage = LLMUsage(provider, 8, 2, total_tokens=10)
    reply = LLMResponse(None, call, usage, {"provider": provider, "content": native})
    with pytest.raises(LLMProtocolError):
        validate_replay_metadata(reply)
    page = FakePage(["Menu"])
    page.click = AsyncMock()
    model = make_llm([reply])
    result = await Runner(model, page, Trace()).run("click menu")
    assert result.outcome == "action_error" and result.success is False
    assert result.model_calls == 1 and result.tokens == 10
    page.click.assert_not_awaited()


def test_supported_anthropic_native_extras_survive_shared_validation():
    call = ToolCall("snapshot", {}, "one")
    parts = [
        {"type": "thinking", "thinking": "private", "signature": "opaque-signature"},
        {"type": "redacted_thinking", "data": "opaque-data"},
        {"type": "text", "text": "source", "citations": [{"type": "char_location",
            "cited_text": "source", "document_index": 0, "document_title": "Doc",
            "file_id": "file", "start_char_index": 0, "end_char_index": 6}]},
        {"type": "tool_use", "name": call.name, "input": call.arguments, "id": call.id,
         "caller": {"type": "direct"}, "toolset_name": "custom"},
    ]
    reply = LLMResponse("source", call, replay_metadata={"provider": "anthropic", "content": parts})
    validate_replay_metadata(reply)
    assert reply.replay_metadata["content"] == parts


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [{"bad": "text"}, ["bad text"], 7])
async def test_native_openai_malformed_assistant_text_retains_usage(content):
    httpx = _http("openai")
    payload = _native("openai", 0, 2)
    payload["choices"][0]["message"]["content"] = content
    adapter = await _client("openai", lambda request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(LLMProtocolError, match="assistant content") as caught:
            await adapter.complete([{"role": "user", "content": "Goal"}], [])
        assert caught.value.usage.input_tokens == 8
        assert caught.value.usage.output_tokens == 2
        assert caught.value.usage.total_tokens == 10
    finally:
        await _close(adapter, "openai")
