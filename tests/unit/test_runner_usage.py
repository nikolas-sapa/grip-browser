from __future__ import annotations

import asyncio

import pytest

from grip.adapters.base import LLMProtocolError, LLMResponse, LLMUsage, ToolCall
from grip.runner import Runner
from grip.trace import Trace, TraceEntry
from tests.unit.test_runner import FakePage


class _LLM:
    def __init__(self, responses):
        self.responses = iter(responses)

    async def complete(self, messages, tools):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.parametrize("usage,expected", [
    (LLMUsage("openai", 100, 20, 10, thought_tokens=5, total_tokens=120), 120),
    (LLMUsage("anthropic", 3, 4, 5, 6), 18),
    (LLMUsage("gemini", 10, 7, 5, thought_tokens=3, total_tokens=20), 20),
    (LLMUsage("openai", 0, 0, total_tokens=0), 0),
    (None, None),
    (LLMUsage("anthropic", input_tokens=7), None),
    (LLMUsage("anthropic", 3, 4), None),
    (LLMUsage("anthropic", 3, 4, 0, 0), 7),
    (LLMUsage("anthropic", 3, 4, 0), None),
    (LLMUsage("gemini", 10, 7), None),
])
async def test_reported_usage_preserved_without_double_counting(usage, expected):
    trace = Trace()
    result = await Runner(
        _LLM([LLMResponse("final text", None, usage)]), FakePage(["page"]), trace
    ).run("answer")
    assert result.tokens == expected
    assert result.model_calls == 1
    assert trace.model_calls == 1
    assert result.estimated_tokens == 0
    entry = next(e for e in trace.actions if e.action == "model_call")
    assert entry.model_usage == usage
    assert result.usage_complete is (expected is not None)


async def test_missing_usage_on_final_call_keeps_total_unknown():
    result = await Runner(
        _LLM([
            LLMResponse(None, ToolCall("snapshot", {}), LLMUsage("openai", 10, 5, total_tokens=15)),
            LLMResponse("final", None),
        ]), FakePage(["page"]), Trace(),
    ).run("answer")
    assert result.tokens is None and result.model_calls == 2
    assert result.usage["input_tokens"] == 10 and result.usage["output_tokens"] == 5
    assert not result.usage_complete


async def test_usage_and_estimates_are_independent_between_runs():
    trace = Trace()
    trace.add(TraceEntry(0, "snapshot", {}, {}, 999, 0))
    runner = Runner(
        _LLM([
            LLMResponse(None, ToolCall("done", {"result": "first"}),
                        LLMUsage("openai", 90, 10, total_tokens=100)),
            LLMResponse("second", None, LLMUsage("openai", 10, 5, total_tokens=15)),
        ]), FakePage(["page"]), trace,
    )
    first, second = await runner.run("first"), await runner.run("second")
    assert (first.tokens, second.tokens) == (100, 15)
    assert first.model_calls == second.model_calls == 1
    assert first.estimated_tokens == second.estimated_tokens == 0
    assert trace.total_tokens == 999 and trace.model_calls == 2


async def test_provider_error_is_an_unknown_model_call_without_secret_payload():
    trace = Trace()
    result = await Runner(
        _LLM([RuntimeError("secret API request body")]), FakePage(["page"]), trace
    ).run("answer")
    assert result.model_calls == trace.model_calls == 1 and result.tokens is None
    entry = next(e for e in trace.actions if e.action == "model_call")
    assert entry.model_usage is None
    assert "secret API" not in str(entry.to_dict())


async def test_timeout_records_one_unknown_model_call():
    class _Slow:
        async def complete(self, messages, tools):
            await asyncio.sleep(1)

    trace = Trace()
    result = await Runner(_Slow(), FakePage(["page"]), trace, llm_timeout=0.001).run("answer")
    assert result.outcome == "llm_timeout"
    assert result.tokens is None and result.model_calls == trace.model_calls == 1


async def test_protocol_rejection_retains_usage_of_received_response():
    trace = Trace()
    usage = LLMUsage("openai", 10, 5, total_tokens=15)
    result = await Runner(
        _LLM([LLMProtocolError("multiple tool calls", usage)]), FakePage(["page"]), trace
    ).run("answer")
    assert result.outcome == "action_error" and result.tokens == 15
    assert result.usage_complete and result.model_calls == trace.model_calls == 1
    assert next(e for e in trace.actions if e.action == "model_call").model_usage == usage


async def test_external_cancellation_records_attempt_and_propagates():
    started = asyncio.Event()

    class _Paused:
        async def complete(self, messages, tools):
            started.set()
            await asyncio.sleep(60)

    trace = Trace()
    task = asyncio.create_task(Runner(_Paused(), FakePage(["page"]), trace).run("answer"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert trace.model_calls == 1 and trace.model_calls_with_usage == 0
