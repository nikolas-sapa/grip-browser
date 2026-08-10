"""Shared Claude-CLI-backed LLM shim.

Deliberately stdlib-only: this file's *source text* is embedded verbatim into
the browser-use arm's TASK_SCRIPT (see bench_llm_loop.py), which runs in an
isolated venv subprocess and cannot `import benchmarks.*`. Keeping literally
identical subprocess/parsing/timeout code on both arms means a bug or quirk
in the shim affects both arms the same way instead of becoming an asymmetric
confound between grip and browser-use.

No API key is available in this environment (Claude Code subscription only),
so this shims a "chat completion" call on top of `claude -p` rather than the
Anthropic SDK. Two flags are load-bearing and were verified by hand, not
guessed, before being relied on here:
  --disallowedTools "*"   blocks the CLI's own agentic tools (Bash, Read,
                           Edit, ...). Verified with a prompt that tempts
                           tool use ("list the files here") — without this
                           the CLI actually ran a tool and returned a
                           directory listing.
  --strict-mcp-config      "*" alone still left the `advisor` MCP tool
                           reachable in this environment; this flag was
                           needed to fully close it. Both are required
                           together for the CLI to behave as a stateless
                           text-in/text-out completion endpoint.

Each call is a fresh CLI process (no --resume): a session that reuses cache
was considered and rejected — grip's Runner prunes superseded page state out
of the message list it resends every turn (Runner._prune_superseded), and a
resumed CLI session would keep every prior full snapshot in its own
transcript regardless, silently defeating that context optimization and
making grip look artificially worse. Fresh-process-per-turn costs a real,
measured fixed overhead (~9-15k cache-creation tokens, ~$0.05-0.09) on every
single call — see measure_baseline_overhead() below and RESULTS_LLM_LOOP.md
for how that overhead is reported rather than hidden.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any

CLAUDE_BIN = "/Users/nikolassapalidis/.local/bin/claude"


@dataclass
class ClaudeCLIResult:
    text: str
    cost_usd: float | None
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    wall_seconds: float
    raw: dict[str, Any]


class ClaudeCLIError(RuntimeError):
    pass


async def call_claude_cli(
    prompt: str,
    *,
    model: str,
    system_prompt: str | None = None,
    timeout: float = 120.0,
    claude_bin: str = CLAUDE_BIN,
) -> ClaudeCLIResult:
    """One headless, stateless `claude -p` turn. Raises ClaudeCLIError on a
    non-zero exit or an is_error response, and asyncio.TimeoutError (via
    wait_for) on a hang — callers decide what a timeout means for their loop,
    this function does not swallow it.
    """
    args = [
        claude_bin, "-p", prompt,
        "--output-format", "json",
        "--model", model,
        "--disallowedTools", "*",
        "--strict-mcp-config",
    ]
    if system_prompt:
        args += ["--system-prompt", system_prompt]
    t0 = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    wall = time.monotonic() - t0
    if proc.returncode != 0:
        raise ClaudeCLIError(f"claude exited {proc.returncode}: {stderr.decode()[-2000:]}")
    data = json.loads(stdout.decode())
    if data.get("is_error"):
        raise ClaudeCLIError(f"claude reported is_error: {data.get('result')}")
    usage = data.get("usage") or {}
    return ClaudeCLIResult(
        text=data.get("result", ""),
        cost_usd=data.get("total_cost_usd"),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        wall_seconds=wall,
        raw=data,
    )


async def measure_baseline_overhead(model: str, claude_bin: str = CLAUDE_BIN) -> float | None:
    """Cost of a single trivial call with the exact same flags used for every
    real turn: the fixed per-process cost (system prompt + tool-schema cache
    creation) that is NOT the task, but is billed on every call because
    --resume is deliberately not used. Measured once per run and reported
    alongside as-billed costs so a reader can see how much of "cost per
    task" is CLI overhead vs. actual task content."""
    try:
        result = await call_claude_cli(
            "Reply with exactly: OK", model=model, timeout=60.0, claude_bin=claude_bin,
        )
    except (ClaudeCLIError, TimeoutError, OSError):
        return None
    return result.cost_usd


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort JSON object extraction from a CLI text reply: strip code
    fences, then fall back to the first {...} span if the model wrapped the
    JSON in prose despite being told not to. Returns None (never raises) so
    callers can treat "no parseable JSON" as a normal end-of-turn case."""
    cleaned = _FENCE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            return None
    return None
