import pytest
from unittest.mock import AsyncMock, MagicMock
from grip.runner import Runner, RunResult
from grip.adapters.base import LLMResponse, ToolCall
from grip.compression.delta import build_delta
from grip.compression.summarizer import Element, PageSnapshot
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


class FakePage:
    """A page whose snapshots really change, driven through the real build_delta.

    Deliberately not a MagicMock: `mock.delta` is a truthy Mock, so _page_payload
    would take the delta branch on turn one and the delta assertions below would
    go green without a delta ever being computed.
    """

    def __init__(self, labels, navigates=False):
        self._navigates = navigates
        self._labels = list(labels)
        self._n = 0
        self._current_snapshot = None
        self._previous_snapshot = None
        self.delta = None

    async def snapshot(self):
        label = self._labels[min(self._n, len(self._labels) - 1)]
        self._n += 1
        # A per-turn URL makes every delta None, which is how a run that navigates
        # on every step behaves — the only shape in which full PAGE: blocks pile up.
        url = f"https://x.test/{self._n}" if self._navigates else "https://x.test"
        snap = PageSnapshot(
            version=self._n,
            url=url,
            title="T",
            elements=[Element(
                index=0, tag="button", role="button", text=label, placeholder=None,
                in_shadow_dom=False, cx=0, cy=0, ref="e1", handle="h0",
            )],
            text_content=f"the page body says {label} and some stable trailing words",
            tokens_estimated=0,
        )
        self.delta = build_delta(self._previous_snapshot, snap)
        self._previous_snapshot = snap
        self._current_snapshot = snap
        return snap

    async def click(self, target):
        return None

    async def type(self, target, text):
        return None

    async def extract(self, schema):
        # The real Page.extract snapshots and returns data, so it advances the
        # delta baseline without any page state reaching the model.
        await self.snapshot()
        return {k: "value" for k in schema}


def _runner_with(clicks, navigates=False):
    responses = [
        LLMResponse(content=None, tool_call=ToolCall(name="click", arguments={"target": c}))
        for c in clicks
    ]
    responses.append(
        LLMResponse(content=None, tool_call=ToolCall(name="done", arguments={"result": "ok"}))
    )
    return Runner(
        llm=make_llm(responses), page=FakePage(clicks, navigates=navigates), trace=Trace()
    )


@pytest.mark.asyncio
async def test_second_turn_sends_a_delta_not_a_full_snapshot():
    runner = _runner_with(["Next", "Next"])
    await runner.run("do the thing")
    payloads = [m["content"] for m in runner._messages if m.get("role") == "tool"]
    assert any(p.startswith("DELTA") for p in payloads), "no delta was ever sent"


@pytest.mark.asyncio
async def test_superseded_page_state_is_pruned():
    runner = _runner_with(["A", "B", "C"])
    await runner.run("do the thing")
    full = [m for m in runner._messages
            if m.get("role") == "tool" and m["content"].startswith("PAGE:")]
    assert len(full) <= 1, "every turn kept its full snapshot in the transcript"


@pytest.mark.asyncio
async def test_delta_is_not_sent_against_a_baseline_the_model_never_saw():
    """extract() snapshots internally and returns data, so the page's delta
    baseline moves on without anything being transmitted. Sending the next delta
    against that baseline would describe refs the model has never been shown."""
    responses = [
        LLMResponse(content=None, tool_call=ToolCall(name="click", arguments={"target": "A"})),
        LLMResponse(content=None, tool_call=ToolCall(name="extract", arguments={"schema": {"p": "s"}})),
        LLMResponse(content=None, tool_call=ToolCall(name="click", arguments={"target": "B"})),
        LLMResponse(content=None, tool_call=ToolCall(name="done", arguments={"result": "ok"})),
    ]
    runner = Runner(llm=make_llm(responses), page=FakePage(["A", "X", "B"]), trace=Trace())
    await runner.run("do the thing")
    payloads = [m["content"] for m in runner._messages if m.get("role") == "tool"]
    assert payloads[-1].startswith("PAGE:"), (
        "sent a delta whose baseline was the un-transmitted extract() snapshot"
    )


@pytest.mark.asyncio
async def test_pruning_keeps_only_the_newest_full_snapshot_when_every_turn_navigates():
    """The delta path produces no full snapshots at all, so pruning is only ever
    exercised by a run that navigates — which is what this covers."""
    runner = _runner_with(["A", "B", "C"], navigates=True)
    await runner.run("do the thing")
    tool_msgs = [m["content"] for m in runner._messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 3, "expected one tool result per click"
    assert [c.startswith("PAGE:") for c in tool_msgs] == [False, False, True]
    assert tool_msgs[0].startswith("[superseded page state")


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
