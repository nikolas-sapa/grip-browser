import pytest
from unittest.mock import AsyncMock, MagicMock
from grip.runner import Runner, RunResult
from grip.adapters.base import LLMResponse, ToolCall
from grip.trace import Trace


def make_page_mock():
    page = MagicMock()
    page.snapshot = AsyncMock()
    page.click = AsyncMock()
    page.type = AsyncMock()
    page.extract = AsyncMock(return_value={"result": "found"})
    page.observe = AsyncMock(return_value="PAGE: X\nURL: x.com")
    snap = MagicMock()
    snap.tokens_estimated = 40
    snap.version = 1
    page.snapshot.return_value = snap
    return page


def make_llm(responses):
    llm = MagicMock()
    llm.complete = AsyncMock(side_effect=responses)
    return llm


@pytest.mark.asyncio
async def test_runner_calls_done_on_finish():
    page = make_page_mock()
    llm = make_llm([
        LLMResponse(content=None, tool_call=ToolCall(name="done", arguments={"result": "finished"})),
    ])
    runner = Runner(llm=llm, page=page, trace=Trace())
    result = await runner.run("Do something")
    assert isinstance(result, RunResult)


@pytest.mark.asyncio
async def test_runner_executes_click_before_done():
    page = make_page_mock()
    llm = make_llm([
        LLMResponse(content=None, tool_call=ToolCall(name="click", arguments={"target": "button"})),
        LLMResponse(content=None, tool_call=ToolCall(name="done", arguments={"result": "clicked"})),
    ])
    runner = Runner(llm=llm, page=page, trace=Trace())
    await runner.run("Click the button")
    page.click.assert_called_once_with("button")


@pytest.mark.asyncio
async def test_runner_result_has_trace():
    page = make_page_mock()
    llm = make_llm([
        LLMResponse(content=None, tool_call=ToolCall(name="done", arguments={"result": "ok"})),
    ])
    trace = Trace()
    runner = Runner(llm=llm, page=page, trace=trace)
    result = await runner.run("Do task")
    assert result.trace is trace


@pytest.mark.asyncio
async def test_runner_stops_after_max_steps():
    page = make_page_mock()
    llm = make_llm([
        LLMResponse(content=None, tool_call=ToolCall(name="click", arguments={"target": "x"}))
    ] * 30)
    runner = Runner(llm=llm, page=page, trace=Trace(), max_steps=3)
    result = await runner.run("Loop forever")
    assert result is not None
