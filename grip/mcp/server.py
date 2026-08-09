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

TOOL_NAMES = ("open", "snapshot", "click", "type", "read")

_browser: Browser | None = None
_page: Any = None
_summarizer = Summarizer()


def reset_state() -> None:
    """Drop the session handles. Exists for tests; the server holds no state
    worth persisting across a process."""
    global _browser, _page
    _browser = None
    _page = None


async def _ensure_browser() -> Browser:
    global _browser
    if _browser is None:
        _browser = Browser()
    return _browser


def _payload() -> str:
    # grip's differentiator: after the first snapshot a turn sends only what
    # changed, not the page again.
    delta = _page.delta
    if delta is not None:
        return format_delta(delta)
    return _summarizer.format(_page._current_snapshot)


async def call_tool(name: str, arguments: dict) -> str:
    global _page
    if name == "open":
        browser = await _ensure_browser()
        _page = await browser.open(arguments["url"])
        await _page.snapshot()
        return _summarizer.format(_page._current_snapshot)
    if _page is None:
        return "ERROR: call 'open' with a url first"
    if name == "snapshot":
        await _page.snapshot()
        return _payload()
    if name == "click":
        await _page.click(arguments["target"])
        await _page.snapshot()
        return _payload()
    if name == "type":
        await _page.type(arguments["target"], arguments["text"])
        await _page.snapshot()
        return _payload()
    if name == "read":
        doc = await _page.read()
        return doc.text
    return f"ERROR: unknown tool {name!r}"


def main() -> None:
    from mcp.server import MCPServer

    server = MCPServer("grip")

    async def _safe(tool_name: str, **arguments: Any) -> str:
        # An MCP tool must answer, not kill the server: a stale ref or a refused
        # navigation is information the client can act on, a traceback is not.
        try:
            return await call_tool(tool_name, arguments)
        except Exception as e:  # noqa: BLE001
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
