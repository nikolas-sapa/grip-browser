from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from grip.adapters.base import LLMAdapter
from grip.compression.delta import format_delta
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
        self._messages: list[dict[str, Any]] = []
        self._last_sent_version = 0

    # Turn 2 onward, the model already has the page in context; re-sending it costs
    # the full snapshot every turn and, because the transcript grows, re-sends every
    # earlier one too. Measured at 89% of prompt tokens by turn 20.
    def _page_payload(self) -> str:
        snap = self._page._current_snapshot
        delta = self._page.delta
        # A delta is only readable against a baseline the model actually received.
        # extract() snapshots and returns data, and click()/type() snapshot
        # implicitly when the cache is cold (which is the state goto() leaves
        # behind) — both advance the page's baseline without emitting anything.
        # "A delta exists" is therefore not the same question as "the model can
        # apply it", and getting that wrong describes refs it has never seen.
        if delta is not None and delta.previous_version == self._last_sent_version:
            self._last_sent_version = delta.version
            return format_delta(delta)
        self._last_sent_version = snap.version
        return self._summarizer.format(snap)

    # A delta describes a change against the state the model was last shown, so
    # only the newest full snapshot has to stay verbatim. Older ones are the same
    # information the deltas already carry.
    #
    # Scanning only role=="tool" deliberately exempts the opening user message,
    # which carries the goal alongside the first snapshot. That leaves ~600 tokens
    # resident for the whole run and is why the saving measures 65% at 5 turns
    # rather than higher — but it is a constant, not a growth term, so per-turn
    # cost stays flat. The goal belongs in that message; splitting it out to prune
    # the snapshot would trade a real invariant for a fixed-size win.
    def _prune_superseded(self) -> None:
        page_states = [
            i for i, m in enumerate(self._messages)
            if m.get("role") == "tool" and str(m.get("content", "")).startswith("PAGE:")
        ]
        for i in page_states[:-1]:
            self._messages[i] = {
                **self._messages[i],
                "content": "[superseded page state; see the deltas that follow]",
            }

    async def run(self, goal: str) -> RunResult:
        snapshot = await self._page.snapshot()
        page_state = self._summarizer.format(snapshot)
        self._last_sent_version = snapshot.version
        messages = self._messages
        messages[:] = [
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
            self._prune_superseded()

        return RunResult(data=final_result, trace=self._trace, tokens=self._trace.total_tokens)

    async def _dispatch(self, name: str, args: dict) -> Any:
        if name == "snapshot":
            await self._page.snapshot()
            return self._page_payload()
        if name == "click":
            await self._page.click(args["target"])
            await self._page.snapshot()
            return self._page_payload()
        if name == "type":
            await self._page.type(args["target"], args["text"])
            await self._page.snapshot()
            return self._page_payload()
        if name == "extract":
            return await self._page.extract(args.get("schema", {}))
        if name == "observe":
            return await self._page.observe(args["question"])
        if name == "done":
            return args.get("result")
        return f"Unknown tool: {name}"
