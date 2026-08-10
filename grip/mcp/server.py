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

import contextlib
import os
from collections.abc import AsyncIterator
from typing import Any

from grip.browser import Browser
from grip.page import Page

TOOL_NAMES = (
    "open", "goto", "snapshot", "click", "type", "read", "screenshot", "run",
    "list_tabs", "switch_tab", "close_tab",
)

_browser: Browser | None = None
_page: Page | None = None
# The page version the client actually holds, which is not the page's own
# baseline — see Page.payload().
_last_sent_version = 0


def reset_state() -> None:
    """Drop the session handles. Exists for tests; the server holds no state
    worth persisting across a process."""
    global _browser, _page, _last_sent_version
    _browser = None
    _page = None
    _last_sent_version = 0


def _llm_adapter_from_env() -> Any | None:
    """Best-effort: only the 'run' tool needs an adapter, so a missing key isn't
    a startup failure here — it only limits what 'run' can do. Mirrors grip.cli's
    env-var convention (ANTHROPIC_API_KEY / OPENAI_API_KEY) without its
    SystemExit-on-missing behaviour, which is wrong for a long-lived server.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        from grip.adapters.anthropic import AnthropicAdapter

        return AnthropicAdapter()
    if os.environ.get("OPENAI_API_KEY"):
        from grip.adapters.openai import OpenAIAdapter

        return OpenAIAdapter()
    return None


async def _ensure_browser() -> Browser:
    global _browser
    if _browser is None:
        _browser = Browser(llm=_llm_adapter_from_env())
    return _browser


def _require_page() -> Page:
    if _page is None:
        raise RuntimeError("call 'open' with a url first")
    return _page


async def call_tool(name: str, arguments: dict[str, Any]) -> str:
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
            raise RuntimeError(
                "the 'run' tool needs an LLM API key: set ANTHROPIC_API_KEY or "
                "OPENAI_API_KEY"
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
    @server.tool(name="open", description="Open a URL and return its snapshot.")
    async def _open(url: str) -> str:
        return await call_tool("open", {"url": url})

    @server.tool(name="goto", description="Navigate the current page to a URL.")
    async def _goto(url: str) -> str:
        return await call_tool("goto", {"url": url})

    @server.tool(name="snapshot", description="Re-snapshot; returns only what changed.")
    async def _snapshot() -> str:
        return await call_tool("snapshot", {})

    @server.tool(name="click", description="Click an element by description or ref.")
    async def _click(target: str) -> str:
        return await call_tool("click", {"target": target})

    @server.tool(name="type", description="Type text into an input.")
    async def _type(target: str, text: str) -> str:
        return await call_tool("type", {"target": target, "text": text})

    @server.tool(name="read", description="Read the page as citable prose blocks.")
    async def _read() -> str:
        return await call_tool("read", {})

    @server.tool(
        name="screenshot",
        description="Capture a JPEG screenshot of the current page, base64-encoded.",
    )
    async def _screenshot() -> str:
        return await call_tool("screenshot", {})

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
