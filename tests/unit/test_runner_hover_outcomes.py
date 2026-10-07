"""Hover uncertainty must never cause a second pointer dispatch."""
import pytest

from grip.adapters.base import LLMResponse, ToolCall
from grip.errors.types import BrowserError, ErrorType, GripError, RecoveryAction
from grip.runner import Runner
from grip.trace import Trace
from tests.unit.test_runner import FakePage, make_llm


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["typed_dispatch", "dispatch", "snapshot", "payload"])
async def test_hover_uncertainty_stops_after_one_attempt(failure):
    class HoverPage(FakePage):
        def __init__(self):
            super().__init__(["Menu"])
            self.hover_attempts = []

        async def hover(self, target):
            self.hover_attempts.append(target)
            if failure == "typed_dispatch":
                raise GripError(BrowserError(
                    ErrorType.ELEMENT_STALE, "after pointer event", 1.0,
                    [RecoveryAction.RETRY],
                ))
            if failure == "dispatch":
                raise RuntimeError("after pointer event")

        async def snapshot(self):
            if failure == "snapshot" and self.hover_attempts:
                raise GripError(BrowserError(
                    ErrorType.ELEMENT_STALE, "after hover observation", 1.0,
                    [RecoveryAction.RETRY],
                ))
            return await super().snapshot()

        def payload(self, last_sent_version):
            if failure == "payload":
                raise RuntimeError("after hover payload")
            return super().payload(last_sent_version)

    page = HoverPage()
    llm = make_llm([LLMResponse(None, ToolCall("hover", {"target": "Menu"}))] * 3)
    result = await Runner(llm, page, Trace(), max_steps=3).run("reveal menu once")
    assert page.hover_attempts == ["Menu"]
    assert llm.complete.await_count == result.model_calls == 1
    assert result.outcome == "ambiguous_action" and result.success is False
    assert "do not repeat" in result.error
    if failure in {"snapshot", "payload"}:
        assert "observation failed" in result.error
    else:
        assert "outcome uncertain" in result.error
