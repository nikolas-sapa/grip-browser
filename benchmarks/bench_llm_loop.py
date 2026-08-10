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
    .venv/bin/python benchmarks/bench_llm_loop.py --n 4      # first 4 tasks only

No OPENAI_API_KEY or ANTHROPIC_API_KEY is available in this environment (a
Claude Code subscription is, an API key is not). Both arms are therefore
routed through headless `claude -p` (benchmarks/claude_cli_llm.py) instead of
a provider SDK — see that file's docstring for the two CLI flags that took
hand-verification, not guessing, to get right. Requires the browser-use venv
(see bench_browseruse.py's docstring for setup) for the browser-use arm.
"""
from __future__ import annotations

import argparse
import asyncio
import http.server
import json
import os
import shutil
import socket
import statistics
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from grip.browser import Browser
from grip.cdp.launcher import find_chrome
from grip.errors import GripError
from grip.runner import Runner
from grip.trace import Trace

from benchmarks.claude_cli_grip_adapter import ClaudeCLIAdapter
from benchmarks.claude_cli_llm import CLAUDE_BIN, measure_baseline_overhead

# ---------------------------------------------------------------------------
# CONFIG — the constants that make the two arms comparable. Change these
# together, never one at a time, or the arms stop being equal.
# ---------------------------------------------------------------------------

MODEL = "sonnet"                 # same model alias, both arms — resolves to
                                  # claude-sonnet-5 via the CLI at time of writing
TEMPERATURE = 0.2                # NOT actually controllable: the `claude` CLI has
                                  # no temperature flag. Left here only so the report
                                  # header states honestly that it was not set, not
                                  # that it was set to 0.2.
MAX_STEPS = 20                   # same per-attempt turn ceiling, both arms
RETRY_BUDGET = 2                 # up to RETRY_BUDGET+1 attempts per task per arm
IN_LOOP_MAX_FAILURES = 3         # consecutive tool errors before an attempt gives up
                                  # early; passed as browser-use's max_failures and
                                  # enforced on grip's Runner via _BoundedRunner below
USE_VISION = False                # non-negotiable: grip has no image channel; a
                                  # vision-on browser-use run would be paying for a
                                  # channel grip cannot use, which is not a fair cost
                                  # comparison. RESULTS_BROWSERUSE.md made the same call.
# 60s was the original (API) budget. A single trivial CLI call already takes
# ~7-8s cold; a real turn with page-state + tool-schema content will run
# longer. Raised so a slow-but-fine turn isn't misrecorded as a shim timeout
# failure (Runner.run silently `break`s on TimeoutError). Feeds both arms:
# grip directly, and browser-use's bu_task_timeout below.
LLM_TIMEOUT_SECONDS = 120.0

CORPUS_DIR = Path(__file__).parent / "corpus"
FIXTURES_DIR = CORPUS_DIR / "fixtures"
TASKS_PATH = CORPUS_DIR / "tasks.json"

SCRATCH = Path.home() / "scratch" / "browseruse"
BU_PYTHON = SCRATCH / ".venv" / "bin" / "python"
# 1800s (30min) was sized for API calls. A CLI round-trip is ~10-30x slower
# per turn (subprocess + full session bootstrap each call, see
# claude_cli_llm.py's docstring on why --resume isn't used to avoid that).
# This is a safety ceiling for the WHOLE task list run sequentially in one
# subprocess, not a per-call budget — sized generously; see
# RESULTS_LLM_LOOP.md for the measured per-turn time this was set against.
BU_TIMEOUT_SECONDS = 21600  # 6h

# Spliced verbatim into TASK_SCRIPT so the browser-use arm runs the exact
# same CLI-calling code as the grip arm (see claude_cli_llm.py's docstring).
# The `from __future__ import annotations` line is stripped: it's only valid
# as a module's first statement, and here it lands mid-file after
# TASK_SCRIPT's own imports — dropping it doesn't change runtime behavior,
# it only affects annotation evaluation, which nothing here depends on.
_CLI_SHIM_SRC = "\n".join(
    line for line in (Path(__file__).parent / "claude_cli_llm.py").read_text().splitlines()
    if line.strip() != "from __future__ import annotations"
)

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
# Cost accounting: both arms now report a real dollar figure straight from
# the CLI's own total_cost_usd (see claude_cli_llm.py) instead of a static
# price table — there is no PRICE_TABLE anymore because there is no token
# count to multiply against one; the CLI bills its own way (see
# RESULTS_LLM_LOOP.md for the fixed-overhead-per-call caveat this creates).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# grip arm
# ---------------------------------------------------------------------------

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
        adapter = ClaudeCLIAdapter(MODEL, LLM_TIMEOUT_SECONDS)
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
    result["llm_calls"] = sum(a["llm_calls"] for a in result["attempts"])
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
from browser_use.llm.views import ChatInvokeCompletion, ChatInvokeUsage

MODEL = %(model)r
TEMPERATURE = %(temperature)r
MAX_STEPS = %(max_steps)r
RETRY_BUDGET = %(retry_budget)r
MAX_FAILURES = %(max_failures)r
USE_VISION = %(use_vision)r
LLM_TIMEOUT = %(llm_timeout)r


# --- benchmarks/claude_cli_llm.py, spliced in verbatim ---------------------
# Embedded rather than imported: this process runs in the isolated
# browser-use venv (see bench_browseruse.py's docstring) and cannot
# `import benchmarks.*`. Splicing the literal source, not reimplementing it,
# is what keeps the CLI-calling code identical between the two arms.
%(cli_shim_src)s
# --- end claude_cli_llm.py --------------------------------------------------


CLI_LEDGER = []  # cleared per attempt; summed into that attempt's row below


class ChatClaudeCLI:
    """Minimal browser_use.llm.base.BaseChatModel implementation backed by
    the same call_claude_cli() the grip arm uses (benchmarks/
    claude_cli_grip_adapter.py). browser_use.Agent calls
    llm.ainvoke(messages, output_format=<pydantic model>) and expects the
    completion validated into that model back — there is no tool-call
    protocol here the way there is on the grip side, it's structured output.
    calculate_cost is deliberately left off Agent() (see run_one below):
    browser-use's own cost table is keyed by real provider model names and
    has no entry for this CLI shim's model alias, so it would silently
    report None/0 rather than error. Cost is tracked in CLI_LEDGER instead,
    straight from the CLI's own total_cost_usd, the same source of truth
    the grip arm uses.
    """

    model = MODEL
    _verified_api_keys = True

    @property
    def provider(self):
        return "claude-cli"

    @property
    def name(self):
        return MODEL

    @property
    def model_name(self):
        # for legacy support: browser_use.llm.base.BaseChatModel defines
        # this as a Protocol default (`return self.model`), but Protocol
        # default method bodies only apply to explicit subclasses, not to
        # structurally-conforming classes like this one — so it must be
        # implemented here too. Used by agent/cloud_events.py's telemetry
        # event (`agent.llm.model_name`).
        return self.model

    def _flatten(self, messages):
        system = None
        turns = []
        for m in messages:
            if m.role == "system":
                system = m.text
            else:
                turns.append("%%s: %%s" %% (m.role.upper(), m.text))
        return system, "\n\n".join(turns)

    async def ainvoke(self, messages, output_format=None, **kwargs):
        system, transcript = self._flatten(messages)
        if output_format is not None:
            schema = json.dumps(output_format.model_json_schema())
            transcript += (
                "\n\n---\nRespond with ONLY a single JSON object matching "
                "this JSON schema exactly, no prose, no markdown fence:\n" + schema
            )
        result = await call_claude_cli(
            transcript, model=MODEL, system_prompt=system, timeout=LLM_TIMEOUT,
        )
        CLI_LEDGER.append({
            "cost_usd": result.cost_usd,
            "wall_seconds": result.wall_seconds,
            "prompt_tokens": (
                result.input_tokens + result.cache_creation_tokens + result.cache_read_tokens
            ),
            "completion_tokens": result.output_tokens,
        })
        usage = ChatInvokeUsage(
            prompt_tokens=(
                result.input_tokens + result.cache_creation_tokens + result.cache_read_tokens
            ),
            prompt_cached_tokens=result.cache_read_tokens,
            prompt_cache_creation_tokens=result.cache_creation_tokens,
            prompt_image_tokens=None,
            completion_tokens=result.output_tokens,
            total_tokens=(
                result.input_tokens + result.cache_creation_tokens
                + result.cache_read_tokens + result.output_tokens
            ),
        )
        if output_format is None:
            return ChatInvokeCompletion(completion=result.text, usage=usage)
        obj = parse_json_object(result.text)
        if obj is None:
            raise RuntimeError(
                "claude-cli: no parseable JSON for output_format " + output_format.__name__
            )
        return ChatInvokeCompletion(completion=output_format.model_validate(obj), usage=usage)


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
    llm = ChatClaudeCLI()
    attempts = []
    success = False
    for attempt in range(RETRY_BUDGET + 1):
        t0 = time.monotonic()
        CLI_LEDGER.clear()
        session = BrowserSession(
            browser_profile=BrowserProfile(headless=True, executable_path=chrome)
        )
        agent = Agent(
            task=task["goal"],
            llm=llm,
            browser_session=session,
            use_vision=USE_VISION,
            max_failures=MAX_FAILURES,
            calculate_cost=False,  # see ChatClaudeCLI docstring: no price-table entry
            # browser-use renamed this action go_to_url -> navigate (params:
            # url, new_tab) in the installed version; the old key raises a
            # bare KeyError out of _convert_initial_actions before step 1.
            initial_actions=[{"navigate": {"url": task["url"]}}],
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
            # Cost/tokens come from CLI_LEDGER (every real claude-cli call made
            # during this attempt, including browser-use's own summarizer/judge
            # calls if any), not history.usage: browser-use's own accounting is
            # keyed by a model-name price table this CLI shim isn't in.
            ledger_costs = [c["cost_usd"] for c in CLI_LEDGER if c["cost_usd"] is not None]
            row.update({
                "success": bool(verify_raw),
                "verify_raw": verify_raw,
                "final_state": state_raw,
                "turns": history.number_of_steps(),
                "aborted": None,
                "done_result": history.final_result(),
                "llm_calls": len(CLI_LEDGER),
                "prompt_tokens": sum(c["prompt_tokens"] for c in CLI_LEDGER),
                "completion_tokens": sum(c["completion_tokens"] for c in CLI_LEDGER),
                "total_tokens": sum(
                    c["prompt_tokens"] + c["completion_tokens"] for c in CLI_LEDGER
                ),
                "cost_usd": (
                    sum(ledger_costs) if len(ledger_costs) == len(CLI_LEDGER) and CLI_LEDGER
                    else None
                ),
            })
        except Exception as e:
            row.update({
                "success": False, "verify_raw": None, "final_state": None,
                "turns": 0, "aborted": "%%s: %%s" %% (type(e).__name__, e),
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
        "llm_calls": sum(a.get("llm_calls", 0) for a in attempts),
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
                "attempts": [], "attempts_used": 0, "total_tokens": 0, "llm_calls": 0,
                "total_cost_usd": None, "total_wall_seconds": 0.0, "turns": 0,
                "harness_error": "%%s: %%s" %% (type(e).__name__, e),
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
        "use_vision": USE_VISION, "llm_timeout": LLM_TIMEOUT_SECONDS,
        "bu_task_timeout": LLM_TIMEOUT_SECONDS * MAX_STEPS,
        "cli_shim_src": _CLI_SHIM_SRC,
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


def _with_adjusted_cost(rows: list[dict], baseline_cost: float | None) -> list[dict]:
    """Returns rows with a `content_cost_usd` field added: total_cost_usd
    minus (fixed per-call CLI overhead * calls made), i.e. an estimate of
    what this task would have cost with --resume-style caching or a real API
    with the same task content. `baseline_cost` is measured once per run
    (measure_baseline_overhead) against the exact same CLI flags every real
    call used. If baseline_cost is unavailable, content_cost_usd == None on
    every row and callers must treat the adjusted pass as unavailable too."""
    out = []
    for r in rows:
        r = dict(r)
        cost, calls = r.get("total_cost_usd"), r.get("llm_calls")
        if baseline_cost is None or cost is None or calls is None:
            r["content_cost_usd"] = None
        else:
            r["content_cost_usd"] = cost - baseline_cost * calls
        out.append(r)
    return out


def compute_verdict(
    grip_rows: list[dict], bu_rows: list[dict], cost_key: str = "total_cost_usd"
) -> dict[str, Any]:
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
        succ = [r for r in rows if r["success"] and r.get(cost_key) is not None]
        if not succ:
            return None
        total_cost = sum(r[cost_key] for r in rows if r.get(cost_key) is not None)
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


def report(
    grip_rows: list[dict], bu_rows: list[dict], bu_error: str, baseline_cost: float | None = None
) -> dict[str, Any]:
    print(f"\nmodel: {MODEL} (via headless `claude -p`, no API key available)  "
          f"temperature: NOT CONTROLLABLE (no CLI flag; left at whatever the CLI "
          f"defaults to, same on both arms)  max_steps: {MAX_STEPS}  "
          f"retry_budget: {RETRY_BUDGET} (up to {RETRY_BUDGET + 1} attempts)  "
          f"use_vision: {USE_VISION}")
    print(
        "ARM ASYMMETRY (disclosed, not fixed): grip exposes 5 tools "
        "(snapshot/click/type/read/done); browser-use exposes ~15 including "
        "scroll and extract_content. A task grip cannot reach with its tool "
        "set registers as a failure, not an efficiency loss. See module "
        "docstring."
    )
    if baseline_cost is not None:
        print(
            f"\nCLI COST CONFOUND (new to this run, disclosed not fixed): every "
            f"single LLM turn on both arms pays a fixed ~${baseline_cost:.4f} "
            f"CLI-session overhead (system prompt + tool-schema cache creation), "
            f"measured directly via a trivial no-content call with the exact "
            f"same flags. Both arms pay it equally (same flags, same model), so "
            f"the comparison between arms is not biased by it, but 'cost' below "
            f"is NOT comparable to a real API's per-token price. AS-BILLED cost "
            f"is what the CLI reports; CONTENT-ONLY subtracts "
            f"baseline_cost * llm_calls per task as an estimate of task-content "
            f"cost with the overhead stripped out."
        )
    else:
        print(
            "\nCLI COST CONFOUND: baseline overhead measurement failed or was "
            "skipped; AS-BILLED cost figures below include an unknown fixed "
            "per-call CLI overhead that could not be subtracted out."
        )
    if bu_error:
        print(f"\nbrowser-use arm error: {bu_error}")

    # STARTUP FAILURES: a task whose browser-use arm never ran (harness_error
    # from the outer subprocess loop, or every attempt aborted before
    # producing a turn) is NOT the same thing as browser-use running the
    # task and losing. Silently scoring it "no, 0 turns" like a normal loss
    # is exactly the bug this block exists to prevent — flag it loudly
    # instead, both in the table (STARTUP-ERR, not "no") and as its own list.
    def _bu_startup_failed(r: dict) -> str | None:
        if r.get("harness_error"):
            return r["harness_error"]
        attempts = r.get("attempts") or []
        if attempts and all(a.get("turns", 0) == 0 and a.get("aborted") for a in attempts):
            return attempts[-1]["aborted"]
        return None

    startup_failures = [
        (r["task_id"], _bu_startup_failed(r)) for r in bu_rows if _bu_startup_failed(r)
    ]
    if startup_failures:
        print(f"\n*** browser-use FAILED TO START on {len(startup_failures)} task(s) "
              f"(never took a turn — this is a harness/API crash, not a loss): ***")
        for tid, err in startup_failures:
            print(f"    {tid}: {err}")

    # NOTE on the columns below: "turns" is the LAST attempt's turn count
    # (or the successful attempt's, if any succeeded), but "$" and "s" are
    # SUMMED across every retry attempt for the task. On any task with
    # RETRY_BUDGET > 0 and no success, $/turns or s/turns overstates
    # per-turn cost/time by however many attempts were burned — divide by
    # llm_calls (also summed across attempts, printed here) instead if you
    # want a real per-call rate.
    print(f"\n{'task':<12} {'grip ok':>8} {'bu ok':>11} {'grip $':>9} {'bu $':>9} "
          f"{'g calls':>8} {'b calls':>8} "
          f"{'g turns*':>9} {'b turns*':>9} {'grip s':>8} {'bu s':>8}")
    by_g = {r["task_id"]: r for r in grip_rows}
    by_b = {r["task_id"]: r for r in bu_rows}
    startup_failed_ids = {tid for tid, _ in startup_failures}
    def _money(r: dict | None) -> str:
        if not r or r.get("total_cost_usd") is None:
            return "-"
        return f"{r['total_cost_usd']:.4f}"

    def _secs(r: dict | None) -> str:
        return f"{r['total_wall_seconds']:.1f}" if r else "-"

    for tid in sorted(set(by_g) | set(by_b)):
        g, b = by_g.get(tid), by_b.get(tid)
        g_ok = "yes" if g and g["success"] else ("no" if g else "-")
        if tid in startup_failed_ids:
            b_ok = "STARTUP-ERR"
        else:
            b_ok = "yes" if b and b["success"] else ("no" if b else "-")
        g_turns = g["turns"] if g else "-"
        b_turns = b["turns"] if b else "-"
        g_calls = g.get("llm_calls", "-") if g else "-"
        b_calls = b.get("llm_calls", "-") if b else "-"
        print(
            f"{tid:<12} {g_ok:>8} {b_ok:>11} {_money(g):>9} {_money(b):>9} "
            f"{g_calls!s:>8} {b_calls!s:>8} "
            f"{g_turns!s:>9} {b_turns!s:>9} {_secs(g):>8} {_secs(b):>8}"
        )
    print("  (*turns = last/successful attempt only, not summed like $/calls/s — "
          "see note above)")

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

    as_billed = compute_verdict(grip_rows, bu_rows, cost_key="total_cost_usd")
    print(
        f"\n--- VERDICT (AS-BILLED cost, includes fixed CLI overhead): "
        f"{as_billed['verdict']} ---"
    )
    for k, v in as_billed.items():
        if k != "verdict":
            print(f"  {k}: {v}")

    content_only: dict[str, Any] | None = None
    if baseline_cost is not None:
        adj_grip = _with_adjusted_cost(grip_rows, baseline_cost)
        adj_bu = _with_adjusted_cost(bu_rows, baseline_cost)
        content_only = compute_verdict(adj_grip, adj_bu, cost_key="content_cost_usd")
        print(
            f"\n--- VERDICT (CONTENT-ONLY cost, overhead subtracted): "
            f"{content_only['verdict']} ---"
        )
        for k, v in content_only.items():
            if k != "verdict":
                print(f"  {k}: {v}")

    # Headline: whichever framing is less flattering to grip, per this repo's
    # convention (RESULTS_AB.md) of leading with the least flattering number
    # rather than cherry-picking. Success-rate-only WEDGE/NO WEDGE (clause_b)
    # is unaffected by the cost confound either way.
    candidates = [as_billed] + ([content_only] if content_only else [])
    headline = min(
        candidates, key=lambda v: {"WEDGE": 2, "NO WEDGE": 1, "INCONCLUSIVE": 0}[v["verdict"]]
    )
    print(f"\n=== HEADLINE VERDICT: {headline['verdict']} ===")
    if content_only and as_billed["verdict"] != content_only["verdict"]:
        print(
            "  (AS-BILLED and CONTENT-ONLY framings disagree — the cost clause "
            "is sensitive to the CLI overhead confound; see both verdicts above "
            "before trusting either one alone.)"
        )
    return {"as_billed": as_billed, "content_only": content_only, "headline": headline}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

async def run_full(tasks: list[dict]) -> None:
    print("measuring baseline CLI overhead (one trivial call, same flags as every real turn)...")
    baseline_cost = await measure_baseline_overhead(MODEL)
    print(f"baseline overhead: {baseline_cost}")

    server = FixtureServer()
    base = server.start()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    raw_path = RESULTS_DIR / f"raw_{ts}.jsonl"
    grip_rows: list[dict] = []
    try:
        with raw_path.open("w") as f:
            for i, task in enumerate(tasks):
                url = server.url_for(task)
                t0 = time.monotonic()
                row = await run_grip_task(task, url)
                grip_rows.append(row)
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(
                    f"[grip {i + 1}/{len(tasks)}] {task['id']} "
                    f"{'OK' if row['success'] else 'FAIL'} in {time.monotonic() - t0:.1f}s"
                )

            chrome = find_chrome() or ""
            print(f"grip arm done. starting browser-use arm ({len(tasks)} tasks)...")
            bu_rows, bu_error = run_browseruse_tasks(tasks, base, chrome)
            for row in bu_rows:
                f.write(json.dumps(row) + "\n")
    finally:
        server.stop()

    verdict = report(grip_rows, bu_rows, bu_error, baseline_cost)
    summary_path = RESULTS_DIR / f"summary_{ts}.json"
    summary_path.write_text(json.dumps({
        "config": {
            "model": MODEL, "temperature": "not controllable via CLI",
            "max_steps": MAX_STEPS, "retry_budget": RETRY_BUDGET, "use_vision": USE_VISION,
            "baseline_cli_overhead_usd": baseline_cost,
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
    if not os.access(CLAUDE_BIN, os.X_OK) and shutil.which("claude") is None:
        print(
            "claude CLI not found: skipping. A fake/stubbed LLM would validate "
            "grip's plumbing but tell you nothing about browser-use's Agent, which "
            "requires a real chat model — so this stage is either a real (cheap) "
            "CLI call or explicitly not run. It was NOT run."
        )
        return
    smoke_tasks = load_tasks(limit=2)
    print(f"running real `claude -p` calls against: {[t['id'] for t in smoke_tasks]} "
          f"(model={MODEL}, max 1 attempt each; each turn pays the fixed CLI "
          f"session overhead measured in run_full, see measure_baseline_overhead)")
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
