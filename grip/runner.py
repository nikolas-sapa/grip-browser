from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Any

from grip.adapters.base import LLMAdapter
from grip.compression.summarizer import Summarizer
from grip.page import Page
from grip.trace import Trace, TraceEntry

_TOOLS = [
    {"type": "function", "function": {
        "name": "snapshot",
        "description": "Take a fresh snapshot of the current page state.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "click",
        "description": "Click an element on the page.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "Description of element to click."}
        }, "required": ["target"]},
    }},
    {"type": "function", "function": {
        "name": "type",
        "description": "Type text into an input field.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string"},
            "text": {"type": "string"},
        }, "required": ["target", "text"]},
    }},
    {"type": "function", "function": {
        "name": "extract",
        "description": "Extract structured data from the page.",
        "parameters": {"type": "object", "properties": {
            "schema": {"type": "object"},
        }, "required": ["schema"]},
    }},
    {"type": "function", "function": {
        "name": "observe",
        "description": "Ask a question about the page without acting.",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string"},
        }, "required": ["question"]},
    }},
    {"type": "function", "function": {
        "name": "done",
        "description": "Signal task completion with the final result.",
        "parameters": {"type": "object", "properties": {
            "result": {"type": "string"},
        }, "required": ["result"]},
    }},
]


@dataclass
class RunResult:
    data: Any
    trace: Trace
    tokens: int = 0


class Runner:
    def __init__(
        self,
        llm: LLMAdapter,
        page: Page,
        trace: Trace,
        max_steps: int = 20,
    ) -> None:
        self._llm = llm
        self._page = page
        self._trace = trace
        self._max_steps = max_steps
        self._summarizer = Summarizer()

    async def run(self, goal: str) -> RunResult:
        snapshot = await self._page.snapshot()
        page_state = self._summarizer.format(snapshot)
        messages = [
            {"role": "system", "content": (
                "You are a web browsing agent. Complete the user's goal using the "
                "available tools. Call 'done' when finished."
            )},
            {"role": "user", "content": f"Goal: {goal}\n\nCurrent page:\n{page_state}"},
        ]

        final_result = None
        for _ in range(self._max_steps):
            t0 = time.monotonic()
            response = await self._llm.complete(messages=messages, tools=_TOOLS)
            duration_ms = int((time.monotonic() - t0) * 1000)

            if response.tool_call is None:
                break

            tc = response.tool_call
            tool_result = await self._dispatch(tc.name, tc.arguments)

            self._trace.add(TraceEntry(
                timestamp=time.time(),
                action=tc.name,
                input=tc.arguments,
                output={"result": str(tool_result)[:500]},
                tokens_consumed=0,
                duration_ms=duration_ms,
            ))

            if tc.name == "done":
                final_result = tc.arguments.get("result")
                break

            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "0", "type": "function", "function": {
                    "name": tc.name, "arguments": str(tc.arguments),
                }}],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": "0",
                "content": str(tool_result),
            })

        return RunResult(data=final_result, trace=self._trace, tokens=self._trace.total_tokens)

    async def _dispatch(self, name: str, args: dict) -> Any:
        if name == "snapshot":
            snap = await self._page.snapshot()
            return self._summarizer.format(snap)
        if name == "click":
            await self._page.click(args["target"])
            snap = await self._page.snapshot()
            return self._summarizer.format(snap)
        if name == "type":
            await self._page.type(args["target"], args["text"])
            snap = await self._page.snapshot()
            return self._summarizer.format(snap)
        if name == "extract":
            return await self._page.extract(args.get("schema", {}))
        if name == "observe":
            return await self._page.observe(args["question"])
        if name == "done":
            return args.get("result")
        return f"Unknown tool: {name}"
