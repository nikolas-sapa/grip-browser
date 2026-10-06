"""Runner rejects unreplayable calls before browser actions."""
from itertools import permutations
from unittest.mock import AsyncMock

import pytest

from grip.adapters.base import LLMResponse, ToolCall
from grip.runner import Runner
from grip.trace import Trace
from tests.unit.test_runner import FakePage, make_llm


async def test_reused_native_id_rejected_before_second_mutation():
    llm = make_llm([
        LLMResponse(None, ToolCall("click", {"target": "First"}, "native-id")),
        LLMResponse(None, ToolCall("click", {"target": "Second"}, "native-id")),
        LLMResponse("finished", None),
    ])
    runner = Runner(llm, FakePage(["page"]), Trace())
    runner._dispatch = AsyncMock(return_value="clicked")
    result = await runner.run("click")
    assert result.outcome == "action_error" and result.success is False
    assert result.model_calls == llm.complete.await_count == 2
    runner._dispatch.assert_awaited_once_with("click", {"target": "First"})
    assistant = next(message for message in runner._messages if message.get("tool_calls"))
    assert assistant["tool_calls"][0]["id"] == "native-id"


@pytest.mark.parametrize("call_id", ["", 1, [], {}])
async def test_invalid_native_id_rejected_before_dispatch(call_id):
    llm = make_llm([LLMResponse(None, ToolCall("click", {"target": "First"}, call_id))])
    runner = Runner(llm, FakePage(["page"]), Trace())
    runner._dispatch = AsyncMock()
    result = await runner.run("click")
    assert result.outcome == "action_error" and result.success is False
    assert result.model_calls == llm.complete.await_count == 1
    runner._dispatch.assert_not_awaited()
    assert not any(message.get("tool_calls") for message in runner._messages)


@pytest.mark.parametrize("nonempty,empty", list(permutations(("text", "ref", "selector"), 2)))
async def test_wait_for_nonempty_and_empty_conditions_rejected(nonempty, empty):
    runner = Runner(make_llm([
        LLMResponse(None, ToolCall("wait_for", {nonempty: "ready", empty: ""})),
    ]), FakePage(["page"]), Trace())
    runner._dispatch = AsyncMock()
    result = await runner.run("wait")
    assert result.outcome == "action_error" and result.success is False
    runner._dispatch.assert_not_awaited()


@pytest.mark.parametrize("condition", ["text", "ref", "selector"])
async def test_wait_for_single_nonempty_condition_dispatches_once(condition):
    runner = Runner(make_llm([
        LLMResponse(None, ToolCall("wait_for", {condition: "ready"})),
        LLMResponse("finished", None),
    ]), FakePage(["page"]), Trace())
    runner._dispatch = AsyncMock(return_value="ready")
    result = await runner.run("wait")
    assert result.outcome == "model_text"
    runner._dispatch.assert_awaited_once_with("wait_for", {condition: "ready"})
