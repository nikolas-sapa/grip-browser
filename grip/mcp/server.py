"""stdio MCP server exposing grip to any MCP client.

ponytail: one Browser, one Page, no session registry. An MCP client drives a
single conversation; multiplexing is a real feature but not this one, and a dict
of sessions keyed by an id nobody sends is speculative.

list_tabs/switch_tab/close_tab do not change that model — there is still one
Browser and one *active* Page (`_page`, the module-global every other tool
operates on). They just expose the tabs `open` already creates under
Browser._pages, which used to be invisible and unreachable once you'd called
`open` a second time. Switching changes which already-open tab is active;
it never creates a second concurrent "session".

The `mcp` package is imported inside `main()` only — this module must stay
importable on a base install so `grip` never depends on the extra.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import dataclasses
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from grip.adapters import adapter_from_env
from grip.browser import Browser
from grip.errors import GripError
from grip.page import Page

TOOL_NAMES = (
    "open", "goto", "snapshot", "click", "type", "select", "read", "screenshot", "run",
    "list_tabs", "switch_tab", "close_tab", "press", "upload", "links", "popups_blocked",
)

_browser: Browser | None = None
_page: Page | None = None
# The page version the client actually holds, which is not the page's own
# baseline — see Page.payload().
_last_sent_version = 0
# Serializes call_tool end to end. Two overlapping calls — a slow 'run' racing
# a 'click', or 'switch_tab' racing a click on the tab it's leaving — would
# otherwise interleave writes to the _page/_last_sent_version globals above:
# an action lands on the wrong tab, or a client is handed a delta computed
# against a baseline it never actually received. This makes tool calls
# strictly sequential per server, which is the model the module docstring
# above already describes (one Browser, one active Page, one conversation).
# Not reset by reset_state(): asyncio.Lock has not bound to a specific event
# loop until first awaited (Python 3.10+), so one module-level instance is
# safe to reuse across the process, including pytest's per-test event loops.
_lock = asyncio.Lock()


def reset_state() -> None:
    """Drop the session handles. Exists for tests; the server holds no state
    worth persisting across a process."""
    global _browser, _page, _last_sent_version
    _browser = None
    _page = None
    _last_sent_version = 0


async def _ensure_browser() -> Browser:
    global _browser
    if _browser is None:
        # No adapter here, not even best-effort: adapter_from_env() imports the
        # matching provider SDK (grip.adapters.gemini etc.) as soon as its key
        # is set in the environment, and raises ImportError if that provider's
        # extra isn't installed. A host that sets e.g. GEMINI_API_KEY without
        # `pip install grip-browser[gemini]` — a common shape, since API keys
        # and extras are configured independently — used to take down every
        # tool at browser construction, including open/snapshot/click, none of
        # which touch a model. Resolution is deferred to the one tool that
        # actually needs it; see the 'run' branch in _dispatch_tool.
        _browser = Browser()
    return _browser


def _require_page() -> Page:
    if _page is None:
        raise RuntimeError("call 'open' with a url first")
    return _page


async def call_tool(name: str, arguments: dict[str, Any]) -> str:
    """Dispatch one tool call and return its text.

    A GripError carries a recovery taxonomy (see grip.errors.types) that the
    caller needs to act on — runner.py already formats it into the tool result
    it feeds back to a sub-agent (runner.py:196-200). This is that same
    formatting for an MCP client, not a departure from "raise, don't format an
    ERROR string" above: the exception still propagates (still becomes
    is_error=True at the real dispatch path), it just carries the hint in its
    message instead of silently dropping it the way `str(GripError)` does.
    """
    async with _lock:
        try:
            return await _dispatch_tool(name, arguments)
        except GripError as e:
            recovery = ", ".join(a.name for a in e.error.recovery) or "none"
            enriched = dataclasses.replace(
                e.error, message=f"{e.error.message} (suggested recovery: {recovery})"
            )
            raise GripError(enriched) from e


async def _dispatch_tool(name: str, arguments: dict[str, Any]) -> str:
    global _page, _last_sent_version
    if name == "open":
        browser = await _ensure_browser()
        _page = await browser.open(arguments["url"])
        # A fresh page is a fresh baseline: nothing the client holds describes it.
        _last_sent_version = 0
        await _page.snapshot()
        text, _last_sent_version = _page.payload(_last_sent_version)
        return text
    if name == "run":
        browser = await _ensure_browser()
        if browser._llm is None:
            # Resolved here, not at browser construction — see _ensure_browser.
            # adapter_from_env() itself imports the provider SDK matching
            # whichever key is set, which raises ImportError when that
            # provider's extra isn't installed; surface that as an actionable
            # message rather than a bare traceback reaching the MCP client.
            try:
                browser._llm = adapter_from_env()
            except ImportError as e:
                raise RuntimeError(f"the 'run' tool needs an LLM adapter: {e}") from e
            if browser._llm is None:
                raise RuntimeError(
                    "the 'run' tool needs an LLM API key: set ANTHROPIC_API_KEY, "
                    "OPENAI_API_KEY, or GEMINI_API_KEY"
                )
        from grip.runner import Runner

        _page = await browser.open(arguments["url"])
        _last_sent_version = 0
        runner = Runner(llm=browser._llm, page=_page, trace=browser.trace)
        result = await runner.run(arguments["goal"])
        # The page is left open on whatever it ended on, and future snapshot/
        # click/type calls should build on it, so the client's baseline is
        # whatever the runner itself last sent, not zero.
        _last_sent_version = runner._last_sent_version
        if result.data is None:
            # str(None) is the literal string "None" — indistinguishable from a
            # real result. The sub-agent hit max_steps, an LLM timeout, or gave
            # up without ever calling 'done'; say so instead.
            return (
                "run ended without calling done() — no result was produced "
                "(step limit, an LLM timeout, or the agent gave up). The page "
                "is left wherever it last navigated; 'snapshot' to see where."
            )
        return str(result.data)
    if name == "list_tabs":
        browser = await _ensure_browser()
        active_id = _page._target_id if _page is not None else None
        lines = [
            f"{p._target_id}\t{p._current_url or '(not yet loaded)'}"
            + ("\t[active]" if p._target_id == active_id else "")
            for p in browser.pages
        ]
        return "\n".join(lines) if lines else "(no open tabs)"
    if name == "switch_tab":
        browser = await _ensure_browser()
        target = browser.get_page(arguments["target_id"])
        if target is None:
            raise ValueError(f"no open tab with target_id {arguments['target_id']!r}")
        _page = target
        # A different tab is a different page the client has no baseline for —
        # same reasoning as a fresh 'open'.
        _last_sent_version = 0
        await _page.snapshot()
        text, _last_sent_version = _page.payload(_last_sent_version)
        return text
    if name == "close_tab":
        browser = await _ensure_browser()
        target_id = arguments.get("target_id") or None
        closing = browser.get_page(target_id) if target_id else _require_page()
        if closing is None:
            raise ValueError(f"no open tab with target_id {target_id!r}")
        was_active = _page is not None and closing._target_id == _page._target_id
        await closing.close()
        if was_active:
            # Silently repointing at another tab would land the next click/type
            # on a page the client didn't ask for. Same ergonomics as before
            # any tab is open: call 'switch_tab' (or 'open') explicitly.
            _page = None
            _last_sent_version = 0
        return f"closed {closing._target_id}"
    page = _require_page()
    if name == "links":
        # Snapshots fresh rather than reading page._current_snapshot: the page
        # version this advances doesn't have to match what the client last
        # saw — payload()'s baseline guard (render_payload) just falls back to
        # a full snapshot on the next 'snapshot' call if it doesn't.
        snap = await page.snapshot()
        return "\n".join(f"{text}\t{url}" for text, url in snap.links) or "(no links)"
    if name == "popups_blocked":
        return str(page.popups_blocked)
    if name == "press":
        await page.press(arguments["key"])
        await page.snapshot()
        text, _last_sent_version = page.payload(_last_sent_version)
        return text
    if name == "upload":
        await page.upload(arguments["target"], *arguments["paths"])
        await page.snapshot()
        text, _last_sent_version = page.payload(_last_sent_version)
        return text
    if name == "goto":
        await page.goto(arguments["url"])
        await page.snapshot()
        text, _last_sent_version = page.payload(_last_sent_version)
        return text
    if name == "snapshot":
        await page.snapshot()
        text, _last_sent_version = page.payload(_last_sent_version)
        return text
    if name == "click":
        await page.click(arguments["target"])
        await page.snapshot()
        text, _last_sent_version = page.payload(_last_sent_version)
        return text
    if name == "type":
        await page.type(arguments["target"], arguments["text"])
        await page.snapshot()
        text, _last_sent_version = page.payload(_last_sent_version)
        return text
    if name == "select":
        await page.select(arguments["target"], arguments["value"])
        await page.snapshot()
        text, _last_sent_version = page.payload(_last_sent_version)
        return text
    if name == "read":
        doc = await page.read()
        return str(doc.text)
    if name == "screenshot":
        shot = await page.screenshot()
        return shot.b64
    raise ValueError(f"unknown tool {name!r}")


@contextlib.asynccontextmanager
async def _lifespan(_server: Any) -> AsyncIterator[dict[str, Any]]:
    """Closes the Browser on every clean shutdown of the stdio transport.

    Entered/exited by MCPServer.run_stdio_async around the whole session, so a
    client disconnecting (stdin EOF) or the process receiving SIGTERM both
    unwind through here. Before this, `reset_state()` only dropped the Python
    handle — the Chrome process and its temp profile dir were never told to
    stop, so even the clean-exit path leaked a browser.
    """
    try:
        yield {}
    finally:
        global _browser, _page
        if _browser is not None:
            await _browser.close()
        _browser = None
        _page = None


def main() -> None:
    try:
        from mcp.server import MCPServer
    except ModuleNotFoundError as e:  # pragma: no cover — needs a base install
        # A bare ModuleNotFoundError from a console script tells the user nothing
        # about the extra they were meant to install.
        raise SystemExit(
            "grip-mcp needs the optional mcp package: "
            'pip install "grip-browser[mcp]"'
        ) from e

    server = MCPServer("grip", lifespan=_lifespan)

    # Tool functions raise on failure rather than formatting an "ERROR: ..."
    # string. MCPServer's real dispatch path (_handle_call_tool, used by
    # server.run()) catches exactly this and turns it into a proper MCP tool
    # result with is_error=True — the client can tell a failure from content by
    # the protocol field instead of by pattern-matching text.
    #
    # The signatures are the tool schemas — MCPServer derives inputSchema from
    # the annotations, so each wrapper is one line over the shared dispatch.
    _SNAPSHOT_SHAPES = (
        "Returns a full page state (`PAGE: <title>` / `URL:` / `INTERACTIVE:` "
        "elements as `[tag:ref] 'label'`, e.g. `[btn:e5] 'Submit'`, CONTENT "
        "truncated to 2000 chars — use 'read' for the full prose) the first "
        "time, or `DELTA v<from>-><to>` (added/changed elements as `[tag:ref]`, "
        "removed as bare `[ref]`, plus CONTENT word-diff ops, or "
        "`DELTA vN->vM: no change`) once a baseline exists — falling back to a "
        "full snapshot whenever the delta wouldn't actually be smaller."
    )
    _TARGET_NOTE = (
        "target is an exact ref from the last snapshot (e.g. 'e5') or a "
        "case-insensitive substring of the element's text/role/placeholder."
    )

    @server.tool(
        name="open",
        description=f"Open a URL and return its snapshot. {_SNAPSHOT_SHAPES}",
    )
    async def _open(url: str) -> str:
        return await call_tool("open", {"url": url})

    @server.tool(name="goto", description="Navigate the current page to a URL.")
    async def _goto(url: str) -> str:
        return await call_tool("goto", {"url": url})

    @server.tool(name="snapshot", description=f"Re-snapshot the page. {_SNAPSHOT_SHAPES}")
    async def _snapshot() -> str:
        return await call_tool("snapshot", {})

    @server.tool(name="click", description=f"Click an element. {_TARGET_NOTE}")
    async def _click(target: str) -> str:
        return await call_tool("click", {"target": target})

    @server.tool(
        name="type",
        description=(
            f"Type text into an input/textarea. {_TARGET_NOTE} Matches only "
            "input/textarea/textbox elements (also against their placeholder)."
        ),
    )
    async def _type(target: str, text: str) -> str:
        return await call_tool("type", {"target": target, "text": text})

    @server.tool(
        name="select",
        description=(
            "Choose an option in a <select> dropdown, by visible option text "
            f"(preferred) or its value attribute. {_TARGET_NOTE} Matches only "
            "<select> elements."
        ),
    )
    async def _select(target: str, value: str) -> str:
        return await call_tool("select", {"target": target, "value": value})

    @server.tool(name="read", description="Read the page as citable prose blocks.")
    async def _read() -> str:
        return await call_tool("read", {})

    @server.tool(name="press", description="Press a key (e.g. 'Enter', 'Tab') on the page.")
    async def _press(key: str) -> str:
        return await call_tool("press", {"key": key})

    @server.tool(
        name="upload",
        description=(
            "Set one or more local file paths on a <input type=file>. "
            f"{_TARGET_NOTE}"
        ),
    )
    async def _upload(target: str, paths: list[str]) -> str:
        return await call_tool("upload", {"target": target, "paths": paths})

    @server.tool(
        name="links",
        description=(
            "Re-snapshot and list every fetchable link's text and absolute "
            "URL, tab-separated one per line — hrefs are left out of "
            "snapshot/DELTA text to keep the token budget down."
        ),
    )
    async def _links() -> str:
        return await call_tool("links", {})

    @server.tool(
        name="popups_blocked",
        description=(
            "Count of window.open()/target=\"_blank\" attempts refused by popup "
            "blocking so far. Nonzero after a click that should have opened a "
            "new tab explains why nothing happened."
        ),
    )
    async def _popups_blocked() -> str:
        return await call_tool("popups_blocked", {})

    @server.tool(
        name="screenshot",
        description=(
            "Capture a JPEG screenshot of the current page as an image "
            "content block (a file path if the client can't accept one)."
        ),
        structured_output=False,
    )
    async def _screenshot() -> Any:
        b64 = await call_tool("screenshot", {})
        data = base64.b64decode(b64)
        try:
            from mcp.server.mcpserver.utilities.types import Image
        except ImportError:  # pragma: no cover — depends on the mcp version installed
            fd, path = tempfile.mkstemp(prefix="grip-screenshot-", suffix=".jpg")
            os.close(fd)
            Path(path).write_bytes(data)  # noqa: ASYNC240 — local write, not I/O we need off-thread
            return path
        return Image(data=data, format="jpeg")

    @server.tool(
        name="list_tabs",
        description="List open tabs (target_id and url, active tab marked).",
    )
    async def _list_tabs() -> str:
        return await call_tool("list_tabs", {})

    @server.tool(
        name="switch_tab",
        description=(
            "Make an already-open tab active; snapshot/click/type/read/goto "
            "operate on it from then on."
        ),
    )
    async def _switch_tab(target_id: str) -> str:
        return await call_tool("switch_tab", {"target_id": target_id})

    @server.tool(
        name="close_tab",
        description=(
            "Close a tab by target_id, or the active tab if target_id is "
            "omitted. Closing the active tab requires 'switch_tab' or 'open' "
            "before the next snapshot/click/type call."
        ),
    )
    async def _close_tab(target_id: str = "") -> str:
        return await call_tool("close_tab", {"target_id": target_id})

    @server.tool(
        name="run",
        description=(
            "Drive the browser toward a goal autonomously (snapshot/click/type/"
            "read in a loop) and return the final result. Requires "
            "ANTHROPIC_API_KEY or OPENAI_API_KEY in the server's environment."
        ),
    )
    async def _run(goal: str, url: str) -> str:
        return await call_tool("run", {"goal": goal, "url": url})

    server.run("stdio")


if __name__ == "__main__":
    main()
