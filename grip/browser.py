from __future__ import annotations
import asyncio
import json
import urllib.parse
from typing import TYPE_CHECKING

from grip.cdp.engine import CDPEngine
from grip.cdp.launcher import ChromeLauncher
from grip.page import Page
from grip.trace import Trace

if TYPE_CHECKING:
    from grip.adapters.base import LLMAdapter

_MACROS: dict[str, str] = {
    "@google_search":    "https://www.google.com/search?q={query}",
    "@youtube_search":   "https://www.youtube.com/results?search_query={query}",
    "@amazon_search":    "https://www.amazon.com/s?k={query}",
    "@github_search":    "https://github.com/search?q={query}",
    "@reddit_search":    "https://www.reddit.com/search/?q={query}",
    "@wikipedia_search": "https://en.wikipedia.org/wiki/Special:Search?search={query}",
    "@twitter_search":   "https://twitter.com/search?q={query}",
    "@yelp_search":      "https://www.yelp.com/search?find_desc={query}",
}


def _expand_macro(url: str, **kwargs: str) -> str:
    if not url.startswith("@"):
        return url
    template = _MACROS.get(url)
    if not template:
        raise ValueError(f"Unknown macro: {url!r}. Available: {sorted(_MACROS)}")
    query = urllib.parse.quote_plus(kwargs.get("query", ""))
    return template.format(query=query)


async def fetch_tab_ws_url(port: int) -> str:
    import urllib.request
    import time

    def _do_fetch() -> list:
        with urllib.request.urlopen(
            f"http://localhost:{port}/json", timeout=2
        ) as resp:
            return json.loads(resp.read())

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            tabs = await asyncio.to_thread(_do_fetch)
            for tab in tabs:
                if tab.get("type") == "page":
                    return tab["webSocketDebuggerUrl"]
        except Exception:
            pass
        await asyncio.sleep(0.2)
    raise RuntimeError(f"No Chrome tab found on port {port}")


class Browser:
    def __init__(
        self,
        llm: "LLMAdapter | None" = None,
        headless: bool = True,
        safe: bool = False,
        proxy: str | None = None,
    ) -> None:
        self._llm = llm
        self._headless = headless
        self._safe = safe
        self._proxy = proxy
        self._launcher: ChromeLauncher | None = None
        self._engine: CDPEngine | None = None
        self.trace = Trace()

    async def __aenter__(self) -> "Browser":
        self._launcher = ChromeLauncher()
        port = self._launcher.launch(headless=self._headless, proxy=self._proxy)
        ws_url = await fetch_tab_ws_url(port)
        self._engine = CDPEngine()
        await self._engine.connect(ws_url)
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    async def open(self, url: str, **kwargs: str) -> Page:
        if not self._engine:
            self._launcher = ChromeLauncher()
            port = self._launcher.launch(headless=self._headless, proxy=self._proxy)
            ws_url = await fetch_tab_ws_url(port)
            self._engine = CDPEngine()
            await self._engine.connect(ws_url)

        url = _expand_macro(url, **kwargs)

        if not url.startswith(("http", "about:", "data:", "file:", "blob:")):
            url = "https://" + url

        await self._engine.send("Page.navigate", {"url": url})
        await self._engine.send("Page.enable")

        load_event = asyncio.Event()

        def on_load(params):
            load_event.set()

        self._engine.on("Page.loadEventFired", on_load)
        try:
            await asyncio.wait_for(load_event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            pass
        finally:
            self._engine.off("Page.loadEventFired", on_load)

        return Page(engine=self._engine, trace=self.trace, safe=self._safe)

    async def run(self, goal: str, url: str) -> "RunResult":
        from grip.runner import Runner
        page = await self.open(url)
        runner = Runner(llm=self._llm, page=page, trace=self.trace)
        return await runner.run(goal)

    async def close(self) -> None:
        if self._engine:
            await self._engine.disconnect()
            self._engine = None
        if self._launcher:
            self._launcher.terminate()
            self._launcher = None
