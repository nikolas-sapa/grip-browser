"""grip.adapters.base.LLMAdapter implementation backed by the Claude CLI.

Flattens the OpenAI-shaped messages/tools grip's Runner builds into a single
text prompt and asks for one JSON tool-call decision back, the same shape
grip/adapters/gemini.py's `_parse_args` documents runner.py needing to
handle: tool_call arguments come back through `str(dict)` in the assistant
message history, not JSON — irrelevant here since this adapter only ever
*emits* tool calls (it doesn't need to re-parse its own prior ones out of
`messages`, those already arrive from Runner as already-executed history),
but the same OpenAI message shape is being read, so it's noted for anyone
extending this file.
"""
from __future__ import annotations

import json
from typing import Any

from grip.adapters.base import LLMResponse, ToolCall

from benchmarks.claude_cli_llm import call_claude_cli, parse_json_object

_INSTRUCTIONS = (
    "\n\n---\nChoose exactly one tool call for the next step. Respond with "
    "ONLY a single JSON object, no prose, no markdown fence:\n"
    '{{"tool": "<tool name>", "arguments": {{<argument object>}}}}\n\n'
    "Available tools:\n{tools_json}"
)


def _flatten(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> tuple[str, str]:
    system_parts: list[str] = []
    turns: list[str] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            system_parts.append(str(m.get("content") or ""))
        elif role == "user":
            turns.append(f"USER: {m.get('content')}")
        elif role == "assistant":
            tool_calls = m.get("tool_calls")
            if tool_calls:
                fn = tool_calls[0]["function"]
                turns.append(f"ASSISTANT (called tool): {fn['name']}({fn['arguments']})")
            elif m.get("content"):
                turns.append(f"ASSISTANT: {m['content']}")
        elif role == "tool":
            turns.append(f"TOOL RESULT: {m.get('content')}")
    tools_json = json.dumps([t["function"] for t in tools], indent=2)
    prompt = "\n\n".join(turns) + _INSTRUCTIONS.format(tools_json=tools_json)
    return "\n\n".join(system_parts), prompt


class ClaudeCLIAdapter:
    """Duck-types grip.adapters.base.LLMAdapter. Keeps its own usage ledger
    the same way benchmarks/bench_llm_loop.py's retired
    _UsageTrackingOpenAIAdapter did, because Runner's own Trace entries
    hardcode tokens_consumed=0 (grip/runner.py) — there is no path in grip
    itself that records billed cost, CLI or API.
    """

    def __init__(self, model: str, timeout: float) -> None:
        self._model = model
        self._timeout = timeout
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        system, prompt = _flatten(messages, tools)
        result = await call_claude_cli(
            prompt, model=self._model, system_prompt=system or None, timeout=self._timeout,
        )
        self.calls.append({
            "cost_usd": result.cost_usd,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cache_creation_tokens": result.cache_creation_tokens,
            "cache_read_tokens": result.cache_read_tokens,
            "wall_seconds": result.wall_seconds,
        })
        obj = parse_json_object(result.text)
        if not obj or "tool" not in obj:
            # No parseable tool call this turn: end the attempt the same way
            # an OpenAI response with no tool_calls does (Runner.run breaks
            # when tool_call is None) rather than silently retrying forever.
            return LLMResponse(content=result.text, tool_call=None)
        return LLMResponse(
            content=None,
            tool_call=ToolCall(
                name=str(obj["tool"]), arguments=dict(obj.get("arguments") or {})
            ),
        )

    def totals(self) -> dict[str, Any]:
        billed = [c["cost_usd"] for c in self.calls if c["cost_usd"] is not None]
        prompt_tok = sum(
            c["input_tokens"] + c["cache_creation_tokens"] + c["cache_read_tokens"]
            for c in self.calls
        )
        completion_tok = sum(c["output_tokens"] for c in self.calls)
        return {
            "prompt_tokens": prompt_tok,
            "completion_tokens": completion_tok,
            "total_tokens": prompt_tok + completion_tok,
            "cost_usd": sum(billed) if len(billed) == len(self.calls) else None,
            "llm_calls": len(self.calls),
            "cli_wall_seconds": sum(c["wall_seconds"] for c in self.calls),
        }
