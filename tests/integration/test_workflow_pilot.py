from unittest.mock import patch

import pytest

from evaluation.workflow_pilot import Ledger, fixture_server, run_pilot
from grip.adapters.base import LLMResponse, ToolCall
from grip.browser import Browser
from grip.runner import Runner


@pytest.mark.asyncio
async def test_real_form_pilot_covers_delayed_confirmation_and_committed_observation_loss():
    result = await run_pilot(attempts=2)
    assert result["passed"], [row["failures"] for row in result["attempts"]]
    assert len(result["attempts"]) == 4
    assert result["summary"] == {
        "clean": {"attempted": 2, "passed": 2},
        "lost_observation": {"attempted": 2, "passed": 2},
    }
    assert sum(row["delay_ms"] == 250 for row in result["attempts"]) == 2
    assert all(row["duplicates"] == 0 for row in result["attempts"])
    assert len({row["attempt"] for row in result["attempts"]}) == 4
    assert all(row["batch_sizes"][0] == 2 for row in result["attempts"])
    assert all(sum(size > 1 for size in row["batch_sizes"]) == 1 for row in result["attempts"])


@pytest.mark.asyncio
async def test_real_safe_read_failure_skips_queued_submit_without_click_or_ledger_entry():
    class SafeReadFailureAdapter:
        async def complete(self, messages, tools):
            return LLMResponse(None, None, tool_calls=(
                ToolCall("snapshot", {}, "read-first"),
                ToolCall("click", {"target": "Submit request"}, "submit-second"),
            ))

    ledger = Ledger()
    with fixture_server(ledger) as base_url:
        async with Browser(allow_private=True) as browser:
            page = await browser.open(f"{base_url}/form/safe-read-control")
            await page._engine.send("Runtime.evaluate", {"expression": (
                "window.pilotClicks=0; document.addEventListener('click',"
                "()=>window.pilotClicks++);"
            )})
            original = page.snapshot
            reads = 0

            async def fail_second_read():
                nonlocal reads
                reads += 1
                if reads == 2:
                    raise RuntimeError("Injected safe-read failure before queued submit")
                return await original()

            with patch.object(page, "snapshot", fail_second_read):
                result = await Runner(SafeReadFailureAdapter(), page, browser.trace,
                                      max_steps=2).run("Read before submitting")
            clicks = await page._engine.send("Runtime.evaluate", {
                "expression": "window.pilotClicks", "returnByValue": True,
            })
            assert result.outcome == "action_error"
            assert result.model_calls == 1
            assert reads == 2
            assert clicks["result"]["value"] == 0
            assert ledger.entries("safe-read-control") == []
