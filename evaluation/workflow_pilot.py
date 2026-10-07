"""Deterministic local form pilot, real Chrome and an independent POST ledger.

Run: python -m evaluation.workflow_pilot --output /path/to/results.json
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import platform
import re
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import grip
from grip.adapters.base import LLMResponse, ToolCall
from grip.browser import Browser
from grip.runner import Runner

SESSION_TIMEOUT = 10.0
CONFIRMATION_TIMEOUT = 2.0
DELAY_MS = 250
ARMS = ("clean", "lost_observation")
_CONFIRMATION = re.compile(r"Confirmation ID: (pilot-[a-z0-9_-]+)")


class Ledger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, list[dict[str, Any]]] = {}
        self.delays: dict[str, int] = {}

    def record(self, attempt: str, fields: dict[str, list[str]]) -> str:
        with self._lock:
            entries = self._entries.setdefault(attempt, [])
            confirmation = f"pilot-{attempt}-{len(entries) + 1}"
            entries.append({"confirmation_id": confirmation, "fields": fields})
            return confirmation

    def entries(self, attempt: str) -> list[dict[str, Any]]:
        with self._lock:
            return [{**entry, "fields": dict(entry["fields"])}
                    for entry in self._entries.get(attempt, [])]


@contextmanager
def fixture_server(ledger: Ledger) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def _attempt(self) -> str | None:
            match = re.fullmatch(r"/form/([a-z0-9_-]+)", urlsplit(self.path).path)
            return match.group(1) if match else None

        def _respond(self, body: str, status: int = 200) -> None:
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self._attempt() is None:
                self._respond("Not found", 404)
                return
            self._respond("""<!doctype html><title>Local form pilot</title>
<form method="post">
<input name="name" aria-label="Name" placeholder="Name" required>
<input type="checkbox" name="consent" value="yes" aria-label="Consent" required>
<select name="plan" aria-label="Plan">
<option value="starter">Starter</option><option value="pro">Pro</option>
</select><button type="submit">Submit request</button></form>""")

        def do_POST(self) -> None:
            attempt = self._attempt()
            if attempt is None:
                self._respond("Not found", 404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            fields = parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)
            confirmation = ledger.record(attempt, fields)
            time.sleep(ledger.delays.get(attempt, 0) / 1000)
            self._respond(f"<!doctype html><title>Confirmation</title>"
                          f"<p>Confirmation ID: {html.escape(confirmation)}</p>")

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


class ScriptedAdapter:
    """Initial two-call response; confirmation comes solely from page observations."""

    def __init__(self, name: str) -> None:
        self.actions = [
            ToolCall("type", {"target": "Name", "text": name}),
            ToolCall("click", {"target": "Consent"}),
            ToolCall("select", {"target": "Plan", "value": "Pro"}),
            ToolCall("click", {"target": "Submit request"}),
            ToolCall("wait_for", {"text": "Confirmation ID:",
                                  "timeout": CONFIRMATION_TIMEOUT}),
        ]
        self.calls: list[str] = []
        self.batch_sizes: list[int] = []
        self.confirmation_id: str | None = None

    async def complete(self, messages: list[dict[str, Any]],
                       tools: list[dict[str, Any]]) -> LLMResponse:
        turn = len(self.calls)
        if turn == 0:
            calls = tuple(self.actions[:2])
        elif turn < len(self.actions):
            calls = (self.actions[turn],)
        else:
            # wait_for may return a no-change delta. Search observed tool states,
            # never the server ledger or a computed expected confirmation ID.
            match = next((found for message in reversed(messages)
                          if message.get("role") == "tool"
                          and (found := _CONFIRMATION.search(str(message.get("content", ""))))),
                         None)
            if match is None:
                raise ValueError("Confirmation missing from observed page state")
            self.confirmation_id = match.group(1)
            calls = (ToolCall("done", {"result": self.confirmation_id}),)
        if any(call.name not in {tool["function"]["name"] for tool in tools} for call in calls):
            raise ValueError("Scripted action missing from advertised tools")
        self.calls.extend(call.name for call in calls)
        self.batch_sizes.append(len(calls))
        identified = tuple(ToolCall(call.name, call.arguments, f"pilot-call-{turn + index}")
                           for index, call in enumerate(calls))
        if len(identified) == 1:
            return LLMResponse(None, identified[0])
        return LLMResponse(None, None, tool_calls=identified)


def check_attempt(row: dict[str, Any]) -> list[str]:
    failures = []
    ledger = row["ledger"]
    if len(ledger) != 1:
        failures.append(f"Expected 1 committed submission, found {len(ledger)}")
    elif ledger[0]["fields"] != row["expected_fields"]:
        failures.append("Server ledger fields differ from expected values")
    if row["submit_calls"] != 1:
        failures.append(f"Expected 1 submit request, found {row['submit_calls']}")
    if sum(size > 1 for size in row["batch_sizes"]) != 1:
        failures.append("Expected exactly 1 plural tool response")
    if row["arm"] == "clean":
        if row["outcome"] != "done" or row["success"] is not True:
            failures.append("Clean Runner did not finish done")
        if ledger and row["observed_confirmation_id"] != ledger[0]["confirmation_id"]:
            failures.append("Observed confirmation does not match server ledger")
        if row["final_url"] != row["initial_url"] or row["document_commits"] < 1:
            failures.append("Same-URL document replacement not observed")
    else:
        if row["outcome"] != "ambiguous_action" or row["success"] is not False:
            failures.append("Lost observation did not produce explicit ambiguity")
        if row["injected_failures"] != 1 or row["model_calls"] != 3:
            failures.append("Expected 1 injected loss and 3 model calls before stop")
    if row["exception"] is not None:
        failures.append(row["exception"])
    return failures


async def run_attempt(base_url: str, ledger: Ledger, arm: str, number: int) -> dict[str, Any]:
    attempt = f"{arm}-{number:02d}"
    expected_name = f"Pilot {number:02d} {arm}"
    url = f"{base_url}/form/{attempt}"
    ledger.delays[attempt] = DELAY_MS if number % 2 == 0 else 0
    adapter = ScriptedAdapter(expected_name)
    row: dict[str, Any] = {
        "attempt": attempt, "arm": arm, "delay_ms": ledger.delays[attempt],
        "initial_url": url, "final_url": None, "document_commits": 0,
        "expected_fields": {"name": [expected_name], "consent": ["yes"], "plan": ["pro"]},
        "ledger": [], "outcome": None, "success": None, "runner_error": None,
        "observed_confirmation_id": None, "model_calls": 0, "submit_calls": 0,
        "batch_sizes": [],
        "injected_failures": 0, "exception": None, "chrome_version": None,
    }
    started = time.monotonic()
    try:
        async with asyncio.timeout(SESSION_TIMEOUT), Browser(allow_private=True) as browser:
            assert browser._engine is not None
            row["chrome_version"] = (await browser._engine.send("Browser.getVersion"))["product"]
            page = await browser.open(url)
            snapshot = page.snapshot

            def committed(params: dict[str, Any]) -> None:
                if not params.get("frame", {}).get("parentId"):
                    row["document_commits"] += 1

            page._engine.on("Page.frameNavigated", committed)

            async def observe() -> Any:
                if arm == "lost_observation" and ledger.entries(attempt):
                    row["injected_failures"] += 1
                    raise RuntimeError("Injected observation loss after server commit")
                return await snapshot()

            with patch.object(page, "snapshot", observe):
                result = await Runner(adapter, page, browser.trace, max_steps=7).run(
                    "Fill Name, check Consent, choose Pro and submit once. "
                    "Return the observed confirmation ID."
                )
            row.update(outcome=result.outcome, success=result.success,
                       runner_error=result.error, model_calls=result.model_calls,
                       observed_confirmation_id=adapter.confirmation_id)
            if arm == "clean":
                row["final_url"] = (await snapshot()).url
    except Exception as exc:
        row["exception"] = f"{type(exc).__name__}: {exc}"
    row["ledger"] = ledger.entries(attempt)
    row["batch_sizes"] = adapter.batch_sizes
    row["submit_calls"] = sum(
        call.name == "click" and call.arguments.get("target") == "Submit request"
        for call in adapter.actions[:len(adapter.calls)]
    )
    row["duration_ms"] = round((time.monotonic() - started) * 1000)
    row["duplicates"] = max(0, len(row["ledger"]) - 1)
    row["failures"] = check_attempt(row)
    row["passed"] = not row["failures"]
    return row


async def run_pilot(attempts: int = 10) -> dict[str, Any]:
    if attempts < 1:
        raise ValueError("attempts must be positive")
    ledger = Ledger()
    rows = []
    with fixture_server(ledger) as base_url:
        for arm in ARMS:
            for number in range(1, attempts + 1):
                rows.append(await run_attempt(base_url, ledger, arm, number))
    return {
        "config": {"attempts_per_arm": attempts, "arms": list(ARMS),
                   "fresh_browser_per_attempt": True, "local_only": True,
                   "session_timeout_seconds": SESSION_TIMEOUT,
                   "confirmation_timeout_seconds": CONFIRMATION_TIMEOUT,
                   "delayed_confirmation_ms": DELAY_MS,
                   "model": "deterministic initial two-call DTO, no provider calls"},
        "versions": {"grip": grip.__version__, "python": platform.python_version(),
                     "chrome": sorted({row["chrome_version"] for row in rows
                                       if row["chrome_version"] is not None})},
        "attempts": rows,
        "summary": {arm: {"attempted": sum(row["arm"] == arm for row in rows),
                          "passed": sum(row["arm"] == arm and row["passed"] for row in rows)}
                    for arm in ARMS},
        "passed": len(rows) == attempts * 2 and all(row["passed"] for row in rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=10)
    args = parser.parse_args()
    result = asyncio.run(run_pilot(args.attempts))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "summary": result["summary"],
                      "passed": result["passed"]}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
