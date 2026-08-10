"""stdio MCP server exposing grip to any MCP client.

ponytail: one Browser, one Page, no session registry. An MCP client drives a
single conversation; multiplexing is a real feature but not this one, and a dict
of sessions keyed by an id nobody sends is speculative.

The `mcp` package is imported inside `main()` only — this module must stay
importable on a base install so `grip` never depends on the extra.
"""
from __future__ import annotations

from typing import Any

from grip.browser import Browser
from grip.compression.delta import format_delta
from grip.compression.summarizer import Summarizer
from grip.page import Page

TOOL_NAMES = ("open", "snapshot", "click", "type", "read")

_browser: Browser | None = None
_page: Page | None = None
_summarizer = Summarizer()
# The page version the client actually holds, which is not the page's own
# baseline — see _payload.
_last_sent_version = 0


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
        _browser = Browser()
    return _browser


def _payload(page: Page) -> str:
    # grip's differentiator: after the first snapshot a turn sends only what
    # changed, not the page again.
    global _last_sent_version
    snap = page._current_snapshot
    delta = page.delta
    # A delta is only readable against a baseline the client actually received.
    # click()/type() snapshot implicitly when the ref cache is cold (which is the
    # state goto() leaves behind), advancing the page's baseline without emitting
    # anything. "A delta exists" is therefore not the same question as "the client
    # can apply it", and getting that wrong describes refs it has never seen.
    if delta is not None and delta.previous_version == _last_sent_version:
        _last_sent_version = delta.version
        return format_delta(delta)
    if snap is None:
        # Every path here snapshots first, so this is a bug in the caller, not a
        # page state. Raising is what a server can afford: main()'s _safe wrapper
        # turns it into one ERROR tool result the client can act on and the
        # process keeps serving, whereas formatting nothing would answer with an
        # empty page as if it were the truth.
        raise RuntimeError(
            "_payload called before any snapshot; the page has no state to send"
        )
    _last_sent_version = snap.version
    return _summarizer.format(snap)


async def call_tool(name: str, arguments: dict[str, Any]) -> str:
    global _page, _last_sent_version
    if name == "open":
        browser = await _ensure_browser()
        _page = await browser.open(arguments["url"])
        # A fresh page is a fresh baseline: nothing the client holds describes it.
        _last_sent_version = 0
        await _page.snapshot()
        return _payload(_page)
    if _page is None:
        return "ERROR: call 'open' with a url first"
    if name == "snapshot":
        await _page.snapshot()
        return _payload(_page)
    if name == "click":
        await _page.click(arguments["target"])
        await _page.snapshot()
        return _payload(_page)
    if name == "type":
        await _page.type(arguments["target"], arguments["text"])
        await _page.snapshot()
        return _payload(_page)
    if name == "read":
        doc = await _page.read()
        return str(doc.text)
    return f"ERROR: unknown tool {name!r}"


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

    server = MCPServer("grip")

    async def _safe(tool_name: str, **arguments: Any) -> str:
        # An MCP tool must answer, not kill the server: a stale ref or a refused
        # navigation is information the client can act on, a traceback is not.
        try:
            return await call_tool(tool_name, arguments)
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"

    # The signatures are the tool schemas — MCPServer derives inputSchema from
    # the annotations, so each wrapper is one line over the shared dispatch.
    @server.tool(name="open", description="Open a URL and return its snapshot.")
    async def _open(url: str) -> str:
        return await _safe("open", url=url)

    @server.tool(name="snapshot", description="Re-snapshot; returns only what changed.")
    async def _snapshot() -> str:
        return await _safe("snapshot")

    @server.tool(name="click", description="Click an element by description or ref.")
    async def _click(target: str) -> str:
        return await _safe("click", target=target)

    @server.tool(name="type", description="Type text into an input.")
    async def _type(target: str, text: str) -> str:
        return await _safe("type", target=target, text=text)

    @server.tool(name="read", description="Read the page as citable prose blocks.")
    async def _read() -> str:
        return await _safe("read")

    server.run("stdio")


if __name__ == "__main__":
    main()
