"""LLM-in-loop benchmark: grip vs browser-use on INTERACTION-heavy tasks.

Every prior benchmark in this repo (bench_agent_ab.py, bench_browseruse.py,
bench_competitors.py) measures observation-payload bytes/tokens with a
*scripted* sequence of actions. No model ever decides what to do, so none of
them measure whether an agent actually completes a task, how many turns it
takes, or what that costs end to end. This script puts a real LLM in the
loop on both arms and measures the thing that was previously unmeasured:

    success (machine-checked, not self-reported), total billed tokens,
    wall-clock seconds, turns to completion, and cost in USD.

Corpus (benchmarks/corpus/generate_fixtures.py): 30 self-hosted, single-page
fixtures — 10 multi-field forms, 10 filter/sort/paginate SPA flows, 10
checkout wizards — each requiring 4+ same-document actions. They are static
HTML+JS served by `python -m http.server` from benchmarks/corpus/fixtures/,
not live public sites: the point of this run is interaction depth, not
real-world markup noise, and 30 live targets would rot (see the corpus
docstring for the one deliberate exception).

Arms, held equal by construction (see CONFIG below — read this before
trusting any number this script prints):
  grip         grip.runner.Runner (production code, not benchmark-only glue)
               driving grip.browser.Browser, 5 tools (snapshot/click/type/
               read/done), text-only observations.
  browser-use  browser_use.Agent, its own tool/action set (15+ actions
               including scroll, extract_content, tabs), use_vision=False
               so neither arm pays for images.
Both: SAME model, SAME temperature, SAME max_steps, SAME per-task attempt
budget. Runs in the isolated browser-use venv via subprocess, same pattern
as bench_browseruse.py, because browser-use's dependency tree must not enter
grip's venv.

ARM ASYMMETRY THAT CANNOT BE FIXED, ONLY DISCLOSED: grip exposes 5 tools,
browser-use exposes ~15 (scroll, tabs, extract_content, go_back, dropdowns,
file writes...). A task solvable by scrolling may be unreachable for grip's
tool set and will show up as a *failure*, not as an efficiency loss. The
corpus is designed so all required actions are reachable without scrolling
(short single-viewport pages), but this is a structural limitation of the
comparison, not a tuning artifact, and every report this script prints
states it again in the header.

Usage:
    .venv/bin/python benchmarks/bench_llm_loop.py --dry-run
    .venv/bin/python benchmarks/bench_llm_loop.py            # full N=30, both arms
                                                               # costs real money
    .venv/bin/python benchmarks/bench_llm_loop.py --n 4      # first 4 tasks only

Requires OPENAI_API_KEY for anything beyond corpus validation. Requires the
browser-use venv (see bench_browseruse.py's docstring for setup) for the
browser-use arm.
"""
from __future__ import annotations

import argparse
import asyncio
import http.server
import json
import os
import socket
import statistics
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from grip.adapters.base import LLMResponse, ToolCall
from grip.browser import Browser
from grip.cdp.launcher import find_chrome
from grip.errors import GripError
from grip.runner import Runner
from grip.trace import Trace

try:
    import openai  # type: ignore[import-not-found]
except ImportError:
    openai = None

# ---------------------------------------------------------------------------
# CONFIG — the constants that make the two arms comparable. Change these
# together, never one at a time, or the arms stop being equal.
# ---------------------------------------------------------------------------

MODEL = "gpt-4o-mini"           # same model, both arms
TEMPERATURE = 0.2                # same temperature, both arms
MAX_STEPS = 20                   # same per-attempt turn ceiling, both arms
RETRY_BUDGET = 2                 # up to RETRY_BUDGET+1 attempts per task per arm
IN_LOOP_MAX_FAILURES = 3         # consecutive tool errors before an attempt gives up
                                  # early; passed as browser-use's max_failures and
                                  # enforced on grip's Runner via _BoundedRunner below
USE_VISION = False                # non-negotiable: grip has no image channel; a
                                  # vision-on browser-use run would be paying for a
                                  # channel grip cannot use, which is not a fair cost
                                  # comparison. RESULTS_BROWSERUSE.md made the same call.
LLM_TIMEOUT_SECONDS = 60.0

# $ per 1M tokens. A snapshot at time of writing, NOT fetched live — verify
# against the provider's pricing page before trusting a real run's dollar
# figures, prices change more often than this file does.
PRICE_TABLE = {
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
    "gpt-4o": {"in": 2.50, "out": 10.00},
}

CORPUS_DIR = Path(__file__).parent / "corpus"
FIXTURES_DIR = CORPUS_DIR / "fixtures"
TASKS_PATH = CORPUS_DIR / "tasks.json"

SCRATCH = Path.home() / "scratch" / "browseruse"
BU_PYTHON = SCRATCH / ".venv" / "bin" / "python"
BU_TIMEOUT_SECONDS = 1800

RESULTS_DIR = CORPUS_DIR / "results"

# Pass criteria (spec, encoded so the verdict is computed, not eyeballed):
#   WEDGE if grip beats browser-use on cost-per-SUCCESSFUL-task by >=1.5x at
#   equal-or-higher success rate (both >=80%), OR grip's success rate is
#   >=10pp higher at equal cost. Anything less: NO WEDGE.
MIN_SUCCESS_RATE = 0.80
COST_WIN_RATIO = 1.5
SUCCESS_WIN_PP = 0.10


def load_tasks(limit: int | None = None) -> list[dict]:
    tasks = json.loads(TASKS_PATH.read_text())
    if limit is not None:
        # Stratified: keep the category mix even when smoke-testing a few tasks.
        by_cat: dict[str, list[dict]] = {}
        for t in tasks:
            by_cat.setdefault(t["category"], []).append(t)
        out: list[dict] = []
        i = 0
        cats = list(by_cat)
        while len(out) < limit and any(by_cat.values()):
            cat = cats[i % len(cats)]
            if by_cat[cat]:
                out.append(by_cat[cat].pop(0))
            i += 1
        return out[:limit]
    return tasks


# ---------------------------------------------------------------------------
# Fixture HTTP server: stdlib, no new dependency, serves the static corpus.
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass


class FixtureServer:
    """Serves benchmarks/corpus/fixtures/ over plain HTTP on 127.0.0.1.

    A background thread, not a subprocess: it only needs to outlive both
    arms' browser sessions in this same process, and a thread avoids a second
    process to manage and kill.
    """

    def __init__(self) -> None:
        self.port = _free_port()
        handler = lambda *a, **kw: _QuietHandler(*a, directory=str(FIXTURES_DIR), **kw)  # noqa: E731
        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def start(self) -> str:
        self._thread.start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def url_for(self, task: dict) -> str:
        return f"http://127.0.0.1:{self.port}/{task['file']}"


# ---------------------------------------------------------------------------
# Cost accounting: shared price table, so a "cost" column means the same
# thing on both arms rather than two different estimation methods.
# ---------------------------------------------------------------------------

def _cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    p = PRICE_TABLE.get(model)
    if p is None:
        return None
    return prompt_tokens / 1e6 * p["in"] + completion_tokens / 1e6 * p["out"]


# ---------------------------------------------------------------------------
# grip arm
# ---------------------------------------------------------------------------

class _UsageTrackingOpenAIAdapter:
    """Duck-types grip.adapters.base.LLMAdapter. Wraps the openai client
    directly rather than grip.adapters.openai.OpenAIAdapter, because that
    adapter's complete() discards response.usage and Runner's own Trace
    entries hardcode tokens_consumed=0 (see grip/runner.py) — there is
    currently no path in grip itself that records billed tokens, so this
    benchmark cannot reuse one and has to keep its own ledger.
    """

    def __init__(self, model: str, temperature: float) -> None:
        if openai is None:
            raise ImportError("pip install openai")
        self._client = openai.AsyncOpenAI()
        self._model = model
        self._temperature = temperature
        self.calls: list[dict[str, int]] = []

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
        }
        if tools:
            kwargs["tools"] = tools
        response = await self._client.chat.completions.create(**kwargs)
        if response.usage:
            self.calls.append({
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            })
        choice = response.choices[0]
        msg = choice.message
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            return LLMResponse(
                content=None,
                tool_call=ToolCall(
                    name=tc.function.name, arguments=json.loads(tc.function.arguments)
                ),
            )
        return LLMResponse(content=msg.content, tool_call=None)

    def totals(self) -> dict[str, Any]:
        prompt = sum(c["prompt_tokens"] for c in self.calls)
        completion = sum(c["completion_tokens"] for c in self.calls)
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "cost_usd": _cost(self._model, prompt, completion),
            "llm_calls": len(self.calls),
        }


class _AttemptAborted(Exception):
    """Raised when a single attempt hits IN_LOOP_MAX_FAILURES consecutive
    tool errors. Distinct from GripError: this is the harness's retry policy,
    not a page condition, so it must not be caught by Runner's own recovery
    path (which is designed to keep going past a single bad action)."""


class _BoundedRunner(Runner):
    """Runner as shipped, with one enforcement point added: abort the
    attempt after IN_LOOP_MAX_FAILURES *consecutive* tool errors, so grip's
    in-loop failure tolerance is bounded the same way browser-use's
    max_failures bounds its Agent. Runner itself has no such cap (a single
    GripError becomes a tool result and the loop continues to max_steps),
    which is correct for production use and wrong for an apples-to-apples
    benchmark, hence the subclass rather than a grip/ change.
    """

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self._consecutive_errors = 0

    async def _dispatch(self, name: str, args: dict[str, Any]) -> Any:
        try:
            result = await super()._dispatch(name, args)
        except GripError:
            self._consecutive_errors += 1
            if self._consecutive_errors >= IN_LOOP_MAX_FAILURES:
                raise _AttemptAborted(
                    f"{IN_LOOP_MAX_FAILURES} consecutive tool errors"
                ) from None
            raise
        self._consecutive_errors = 0
        return result


async def _grip_verify(page, verify_js: str) -> tuple[bool, Any]:
    raw = await page._eval(verify_js)
    return bool(raw), raw


async def _grip_state(page) -> Any:
    try:
        return await page._eval("window.__bench_state()")
    except Exception as e:
        return f"<state unavailable: {e}>"


async def run_grip_task(task: dict, url: str) -> dict:
    result: dict[str, Any] = {"arm": "grip", "task_id": task["id"], "attempts": []}
    for attempt in range(RETRY_BUDGET + 1):
        adapter = _UsageTrackingOpenAIAdapter(MODEL, TEMPERATURE)
        t0 = time.monotonic()
        attempt_row: dict[str, Any] = {"attempt": attempt + 1}
        try:
            # allow_private=True: this benchmark's targets are self-hosted
            # fixtures served on 127.0.0.1 (see FixtureServer above), which
            # the SSRF default-deny policy refuses by default. A local
            # fixture harness is the legitimate use of this opt-out — not a
            # real navigation to an attacker-controlled internal address.
            async with Browser(headless=True, allow_private=True) as browser:
                page = await browser.open(url)
                trace = Trace()
                runner = _BoundedRunner(
                    adapter, page, trace, max_steps=MAX_STEPS, llm_timeout=LLM_TIMEOUT_SECONDS
                )
                try:
                    run_result = await runner.run(task["goal"])
                    aborted = None
                except _AttemptAborted as e:
                    run_result = None
                    aborted = str(e)
                success, raw = await _grip_verify(page, task["verify"])
                state = await _grip_state(page)
                attempt_row.update({
                    "success": success,
                    "verify_raw": raw,
                    "final_state": state,
                    "turns": len(trace.actions),
                    "aborted": aborted,
                    "done_result": run_result.data if run_result else None,
                })
        except (GripError, OSError, TimeoutError, ValueError) as e:
            attempt_row.update({
                "success": False, "verify_raw": None, "final_state": None,
                "turns": 0, "aborted": f"{type(e).__name__}: {e}", "done_result": None,
            })
        attempt_row["wall_seconds"] = time.monotonic() - t0
        attempt_row.update(adapter.totals())
        result["attempts"].append(attempt_row)
        if attempt_row["success"]:
            break
    result["success"] = any(a["success"] for a in result["attempts"])
    result["attempts_used"] = len(result["attempts"])
    result["total_tokens"] = sum(a["total_tokens"] for a in result["attempts"])
    result["total_cost_usd"] = sum(
        a["cost_usd"] for a in result["attempts"] if a["cost_usd"] is not None
    ) if all(a["cost_usd"] is not None for a in result["attempts"]) else None
    result["total_wall_seconds"] = sum(a["wall_seconds"] for a in result["attempts"])
    result["turns"] = next(
        (a["turns"] for a in result["attempts"] if a["success"]),
        result["attempts"][-1]["turns"],
    )
    return result


# ---------------------------------------------------------------------------
# browser-use arm: subprocess into the isolated venv, same pattern as
# bench_browseruse.py's CAPTURE_SCRIPT.
# ---------------------------------------------------------------------------

TASK_SCRIPT = r'''
"""Written by benchmarks/bench_llm_loop.py. Runs in the browser-use venv.

usage: python browseruse_tasks.py TASKS_JSON OUT_JSON CHROME_EXECUTABLE
"""
import asyncio
import json
import sys
import time

from browser_use import Agent
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.llm.openai.chat import ChatOpenAI

MODEL = %(model)r
TEMPERATURE = %(temperature)r
MAX_STEPS = %(max_steps)r
RETRY_BUDGET = %(retry_budget)r
MAX_FAILURES = %(max_failures)r
USE_VISION = %(use_vision)r


async def eval_js(session, expression):
    cdp = await session.get_or_create_cdp_session()
    res = await cdp.cdp_client.send.Runtime.evaluate(
        params={"expression": expression, "returnByValue": True},
        session_id=cdp.session_id,
    )
    result = res.get("result", {})
    if res.get("exceptionDetails"):
        raise RuntimeError(str(res["exceptionDetails"]))
    return result.get("value")


async def run_one(task, chrome):
    llm = ChatOpenAI(model=MODEL, temperature=TEMPERATURE)
    attempts = []
    success = False
    for attempt in range(RETRY_BUDGET + 1):
        t0 = time.monotonic()
        session = BrowserSession(
            browser_profile=BrowserProfile(headless=True, executable_path=chrome)
        )
        agent = Agent(
            task=task["goal"],
            llm=llm,
            browser_session=session,
            use_vision=USE_VISION,
            max_failures=MAX_FAILURES,
            calculate_cost=True,
            initial_actions=[{"go_to_url": {"url": task["url"]}}],
        )
        row = {"attempt": attempt + 1}
        # Agent.run()'s finally block always calls self.close(), which tears
        # the browser down before this script can evaluate the verify
        # expression against the final page. Suppressing that one call and
        # closing manually afterward is the only way to inspect
        # post-task state without editing browser_use itself.
        orig_close = agent.close
        async def _noop():
            return None
        agent.close = _noop
        try:
            history = await asyncio.wait_for(
                agent.run(max_steps=MAX_STEPS), timeout=%(bu_task_timeout)r
            )
            verify_raw = await eval_js(agent.browser_session, task["verify"])
            state_raw = await eval_js(agent.browser_session, "window.__bench_state()")
            usage = history.usage
            row.update({
                "success": bool(verify_raw),
                "verify_raw": verify_raw,
                "final_state": state_raw,
                "turns": history.number_of_steps(),
                "aborted": None,
                "done_result": history.final_result(),
                "prompt_tokens": usage.total_prompt_tokens if usage else None,
                "completion_tokens": usage.total_completion_tokens if usage else None,
                "total_tokens": usage.total_tokens if usage else None,
                "cost_usd": usage.total_cost if usage else None,
            })
        except Exception as e:
            row.update({
                "success": False, "verify_raw": None, "final_state": None,
                "turns": 0, "aborted": "%s: %s" % (type(e).__name__, e),
                "done_result": None, "prompt_tokens": 0, "completion_tokens": 0,
                "total_tokens": 0, "cost_usd": 0.0,
            })
        finally:
            try:
                await orig_close()
            except Exception:
                pass
            try:
                await session.kill()
            except Exception:
                pass
        row["wall_seconds"] = time.monotonic() - t0
        attempts.append(row)
        if row["success"]:
            success = True
            break
    return {
        "arm": "browseruse",
        "task_id": task["id"],
        "success": success,
        "attempts": attempts,
        "attempts_used": len(attempts),
        "total_tokens": sum(a["total_tokens"] or 0 for a in attempts),
        "total_cost_usd": (
            sum(a["cost_usd"] for a in attempts)
            if all(a["cost_usd"] is not None for a in attempts) else None
        ),
        "total_wall_seconds": sum(a["wall_seconds"] for a in attempts),
        "turns": next((a["turns"] for a in attempts if a["success"]), attempts[-1]["turns"]),
    }


async def main():
    tasks = json.loads(open(sys.argv[1]).read())
    out_path = sys.argv[2]
    chrome = sys.argv[3]
    results = []
    for task in tasks:
        try:
            results.append(await run_one(task, chrome))
        except Exception as e:
            results.append({
                "arm": "browseruse", "task_id": task["id"], "success": False,
                "attempts": [], "attempts_used": 0, "total_tokens": 0,
                "total_cost_usd": None, "total_wall_seconds": 0.0, "turns": 0,
                "harness_error": "%s: %s" % (type(e).__name__, e),
            })
    open(out_path, "w").write(json.dumps(results))


asyncio.run(main())
'''


def _bu_env() -> dict[str, str]:
    env = dict(os.environ)
    env["ANONYMIZED_TELEMETRY"] = "false"
    env["BROWSER_USE_CLOUD_SYNC"] = "false"
    return env


def run_browseruse_tasks(
    tasks: list[dict], fixture_base: str, chrome: str
) -> tuple[list[dict], str]:
    """Returns (results, error). error is "" on a clean subprocess exit; a
    non-empty error still returns whatever partial results file existed."""
    if not BU_PYTHON.exists():
        return [], (
            f"missing {BU_PYTHON}; create it with `python3 -m venv {SCRATCH / '.venv'} "
            f"&& {BU_PYTHON} -m pip install browser-use`"
        )
    SCRATCH.mkdir(parents=True, exist_ok=True)
    script_path = SCRATCH / "browseruse_tasks.py"
    script_path.write_text(TASK_SCRIPT % {
        "model": MODEL, "temperature": TEMPERATURE, "max_steps": MAX_STEPS,
        "retry_budget": RETRY_BUDGET, "max_failures": IN_LOOP_MAX_FAILURES,
        "use_vision": USE_VISION, "bu_task_timeout": LLM_TIMEOUT_SECONDS * MAX_STEPS,
    })
    tasks_with_urls = [{**t, "url": f"{fixture_base}/{t['file']}"} for t in tasks]
    with tempfile.TemporaryDirectory() as tmp:
        tasks_path = Path(tmp) / "tasks.json"
        out_path = Path(tmp) / "out.json"
        tasks_path.write_text(json.dumps(tasks_with_urls))
        try:
            proc = subprocess.run(
                [str(BU_PYTHON), str(script_path), str(tasks_path), str(out_path), chrome],
                cwd=SCRATCH, capture_output=True, text=True, env=_bu_env(),
                timeout=BU_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return [], f"browseruse_tasks.py exceeded {BU_TIMEOUT_SECONDS}s"
        if not out_path.exists():
            return [], (
                f"browseruse_tasks.py exited {proc.returncode}: "
                f"{proc.stderr.strip()[-1500:]}"
            )
        return json.loads(out_path.read_text()), ""


# ---------------------------------------------------------------------------
# Corpus validation (--dry-run stage 1): free, no LLM, all 30 tasks.
# ---------------------------------------------------------------------------

_EXPECTED_ANCHOR = {"form": "#f", "spa": "#filter", "wizard": "#step1"}


async def validate_corpus(tasks: list[dict], fixture_base: str) -> list[dict]:
    rows = []
    # allow_private=True: see the matching comment in run_grip_task above.
    async with Browser(headless=True, allow_private=True) as browser:
        for task in tasks:
            row = {"task_id": task["id"], "category": task["category"]}
            try:
                page = await browser.open(f"{fixture_base}/{task['file']}")
                anchor = _EXPECTED_ANCHOR[task["category"]]
                has_anchor = await page._eval(
                    f"document.querySelector({json.dumps(anchor)}) !== null"
                )
                verify_evaluates = await page._eval(task["verify"])
                await page.close()
                row.update({
                    "ok": bool(has_anchor) and isinstance(verify_evaluates, bool),
                    "has_anchor": bool(has_anchor),
                    "verify_type": type(verify_evaluates).__name__,
                    "verify_initial_value": verify_evaluates,
                    "error": None,
                })
            except (GripError, OSError, TimeoutError, ValueError) as e:
                row.update({"ok": False, "error": f"{type(e).__name__}: {e}"})
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _ratio_stats(grip_rows: list[dict], bu_rows: list[dict], key: str) -> dict[str, Any]:
    """Same shape as bench_browseruse.py's _ratio_stats: both medians, named,
    with the less-flattering one marked, plus min/max range."""
    by_id_g = {r["task_id"]: r for r in grip_rows}
    by_id_b = {r["task_id"]: r for r in bu_rows}
    pairs = []
    for tid, g in by_id_g.items():
        b = by_id_b.get(tid)
        if b and g.get(key) not in (None, 0) and b.get(key) not in (None, 0):
            pairs.append((g[key], b[key]))
    if not pairs:
        return {"n": 0}
    ratios = [bu / grip for grip, bu in pairs]  # >1 means grip is cheaper/faster
    grip_med = statistics.median([g for g, _ in pairs])
    bu_med = statistics.median([b for _, b in pairs])
    return {
        "n": len(pairs),
        "median_of_ratios": statistics.median(ratios),
        "ratio_of_medians": bu_med / grip_med if grip_med else None,
        "min_ratio": min(ratios), "max_ratio": max(ratios),
    }


def compute_verdict(grip_rows: list[dict], bu_rows: list[dict]) -> dict[str, Any]:
    g_succ = [r for r in grip_rows if r["success"]]
    b_succ = [r for r in bu_rows if r["success"]]
    g_rate = len(g_succ) / len(grip_rows) if grip_rows else 0.0
    b_rate = len(b_succ) / len(bu_rows) if bu_rows else 0.0

    if not grip_rows or not bu_rows:
        return {"verdict": "INCONCLUSIVE", "reason": "no completed tasks on one or both arms"}
    if g_rate < MIN_SUCCESS_RATE and b_rate < MIN_SUCCESS_RATE:
        return {
            "verdict": "INCONCLUSIVE",
            "reason": (
                f"both arms below {MIN_SUCCESS_RATE:.0%} success "
                f"(grip {g_rate:.0%}, browser-use {b_rate:.0%}); cost-per-success "
                "is dominated by the failure denominator and not trustworthy"
            ),
        }

    def cost_per_success(rows: list[dict]) -> float | None:
        succ = [r for r in rows if r["success"] and r.get("total_cost_usd") is not None]
        if not succ:
            return None
        total_cost = sum(r["total_cost_usd"] for r in rows if r.get("total_cost_usd") is not None)
        n_succ = sum(1 for r in rows if r["success"])
        return total_cost / n_succ if n_succ else None

    g_cps = cost_per_success(grip_rows)
    b_cps = cost_per_success(bu_rows)

    clause_a = (
        g_cps is not None and b_cps is not None and g_cps > 0
        and g_rate >= MIN_SUCCESS_RATE and b_rate >= MIN_SUCCESS_RATE
        and (b_cps / g_cps) >= COST_WIN_RATIO
    )
    clause_b = (g_rate - b_rate) >= SUCCESS_WIN_PP

    verdict = "WEDGE" if (clause_a or clause_b) else "NO WEDGE"
    clause = "cost-per-success >=1.5x at equal-or-higher success" if clause_a else (
        "success rate >=10pp higher at equal cost" if clause_b else "neither clause met"
    )
    return {
        "verdict": verdict, "clause": clause,
        "grip_success_rate": g_rate, "browseruse_success_rate": b_rate,
        "grip_cost_per_success": g_cps, "browseruse_cost_per_success": b_cps,
        "cost_ratio_bu_over_grip": (b_cps / g_cps) if (g_cps and b_cps) else None,
    }


def report(grip_rows: list[dict], bu_rows: list[dict], bu_error: str) -> dict[str, Any]:
    print(f"\nmodel: {MODEL}  temperature: {TEMPERATURE}  max_steps: {MAX_STEPS}  "
          f"retry_budget: {RETRY_BUDGET} (up to {RETRY_BUDGET + 1} attempts)  "
          f"use_vision: {USE_VISION}")
    print(
        "ARM ASYMMETRY (disclosed, not fixed): grip exposes 5 tools "
        "(snapshot/click/type/read/done); browser-use exposes ~15 including "
        "scroll and extract_content. A task grip cannot reach with its tool "
        "set registers as a failure, not an efficiency loss. See module "
        "docstring."
    )
    if bu_error:
        print(f"\nbrowser-use arm error: {bu_error}")

    print(f"\n{'task':<12} {'grip ok':>8} {'bu ok':>6} {'grip $':>9} {'bu $':>9} "
          f"{'grip turns':>11} {'bu turns':>9} {'grip s':>8} {'bu s':>8}")
    by_g = {r["task_id"]: r for r in grip_rows}
    by_b = {r["task_id"]: r for r in bu_rows}
    def _money(r: dict | None) -> str:
        if not r or r.get("total_cost_usd") is None:
            return "-"
        return f"{r['total_cost_usd']:.4f}"

    def _secs(r: dict | None) -> str:
        return f"{r['total_wall_seconds']:.1f}" if r else "-"

    for tid in sorted(set(by_g) | set(by_b)):
        g, b = by_g.get(tid), by_b.get(tid)
        g_ok = "yes" if g and g["success"] else ("no" if g else "-")
        b_ok = "yes" if b and b["success"] else ("no" if b else "-")
        g_turns = g["turns"] if g else "-"
        b_turns = b["turns"] if b else "-"
        print(
            f"{tid:<12} {g_ok:>8} {b_ok:>6} {_money(g):>9} {_money(b):>9} "
            f"{g_turns!s:>11} {b_turns!s:>9} {_secs(g):>8} {_secs(b):>8}"
        )

    print(
        "\nmedians (median_of_ratios | ratio_of_medians; "
        "ratio = browser-use/grip, >1 means grip cheaper/faster):"
    )
    for key, label in [("total_cost_usd", "cost $"), ("total_tokens", "tokens"),
                        ("total_wall_seconds", "wall seconds"), ("turns", "turns")]:
        s = _ratio_stats(grip_rows, bu_rows, key)
        if not s.get("n"):
            print(f"  {label:<14} unmeasured")
            continue
        print(f"  {label:<14} n={s['n']}  median_of_ratios={s['median_of_ratios']:.2f}x  "
              f"ratio_of_medians={s['ratio_of_medians']:.2f}x  "
              f"range {s['min_ratio']:.2f}x-{s['max_ratio']:.2f}x")

    verdict = compute_verdict(grip_rows, bu_rows)
    print(f"\n--- VERDICT: {verdict['verdict']} ---")
    for k, v in verdict.items():
        if k != "verdict":
            print(f"  {k}: {v}")
    return verdict


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def run_full(tasks: list[dict]) -> None:
    server = FixtureServer()
    base = server.start()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    raw_path = RESULTS_DIR / f"raw_{ts}.jsonl"
    grip_rows: list[dict] = []
    try:
        with raw_path.open("w") as f:
            for task in tasks:
                url = server.url_for(task)
                row = await run_grip_task(task, url)
                grip_rows.append(row)
                f.write(json.dumps(row) + "\n")
                f.flush()

            chrome = find_chrome() or ""
            bu_rows, bu_error = run_browseruse_tasks(tasks, base, chrome)
            for row in bu_rows:
                f.write(json.dumps(row) + "\n")
    finally:
        server.stop()

    verdict = report(grip_rows, bu_rows, bu_error)
    summary_path = RESULTS_DIR / f"summary_{ts}.json"
    summary_path.write_text(json.dumps({
        "config": {
            "model": MODEL, "temperature": TEMPERATURE, "max_steps": MAX_STEPS,
            "retry_budget": RETRY_BUDGET, "use_vision": USE_VISION,
        },
        "verdict": verdict, "n_tasks": len(tasks),
        "grip_rows": grip_rows, "browseruse_rows": bu_rows, "browseruse_error": bu_error,
    }, indent=2))
    print(f"\nraw per-task JSONL: {raw_path}")
    print(f"summary JSON: {summary_path}")


async def run_dry_run() -> None:
    all_tasks = load_tasks()
    print(f"--- dry-run stage 1: corpus validation, no LLM, all {len(all_tasks)} tasks ---")
    server = FixtureServer()
    base = server.start()
    try:
        rows = await validate_corpus(all_tasks, base)
    finally:
        server.stop()
    n_ok = sum(1 for r in rows if r["ok"])
    print(f"{n_ok}/{len(rows)} tasks validated (page loads, anchor element present, "
          f"verify() evaluates to a bool)")
    for r in rows:
        if not r["ok"]:
            print(f"  FAIL {r['task_id']}: {r}")

    print("\n--- dry-run stage 2: both-arms smoke test on 2 tasks ---")
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY not set: skipping. A fake/stubbed LLM would validate "
            "grip's plumbing but tell you nothing about browser-use's Agent, which "
            "requires a real chat model — so this stage is either a real (cheap) "
            "API call or explicitly not run. It was NOT run."
        )
        return
    smoke_tasks = load_tasks(limit=2)
    print(f"running real API calls against: {[t['id'] for t in smoke_tasks]} "
          f"(model={MODEL}, max 1 attempt each, ~$0.01-0.05 total at gpt-4o-mini rates)")
    server = FixtureServer()
    base = server.start()
    try:
        global RETRY_BUDGET
        saved = RETRY_BUDGET
        RETRY_BUDGET = 0  # smoke test: 1 attempt, keep cost minimal
        grip_rows = []
        for task in smoke_tasks:
            grip_rows.append(await run_grip_task(task, server.url_for(task)))
        chrome = find_chrome() or ""
        bu_rows, bu_error = run_browseruse_tasks(smoke_tasks, base, chrome)
        RETRY_BUDGET = saved
    finally:
        server.stop()
    report(grip_rows, bu_rows, bu_error)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--n", type=int, default=None, help="limit corpus to N tasks (stratified across categories)"
    )
    args = parser.parse_args()

    if args.dry_run:
        asyncio.run(run_dry_run())
        return

    tasks = load_tasks(limit=args.n)
    asyncio.run(run_full(tasks))


if __name__ == "__main__":
    main()
