from __future__ import annotations
import asyncio
import contextlib
import json
import logging
import urllib.parse
from typing import TYPE_CHECKING

from grip.cdp.engine import CDPEngine
from grip.cdp.launcher import ChromeLauncher
from grip.page import Page
from grip.trace import Trace

if TYPE_CHECKING:
    from grip.adapters.base import LLMAdapter

logger = logging.getLogger(__name__)

_MACROS: dict[str, str] = {
    "@google_search":       "https://www.google.com/search?q={query}",
    "@youtube_search":      "https://www.youtube.com/results?search_query={query}",
    "@amazon_search":       "https://www.amazon.com/s?k={query}",
    "@github_search":       "https://github.com/search?q={query}",
    "@reddit_search":       "https://www.reddit.com/search/?q={query}",
    "@wikipedia_search":    "https://en.wikipedia.org/wiki/Special:Search?search={query}",
    "@twitter_search":      "https://twitter.com/search?q={query}",
    "@yelp_search":         "https://www.yelp.com/search?find_desc={query}",
    "@seekingalpha_search": "https://seekingalpha.com/search?q={query}",
    "@reuters_search":      "https://www.reuters.com/search/news?blob={query}",
    "@wsj_search":          "https://www.wsj.com/search?query={query}&mod=searchresults_viewallresults",
    "@reddit_wsb":          "https://www.reddit.com/r/wallstreetbets/search/?q={query}&restrict_sr=1&sort=new",
}


def _expand_macro(url: str, **kwargs: str) -> str:
    if not url.startswith("@"):
        return url
    template = _MACROS.get(url)
    if not template:
        raise ValueError(f"Unknown macro: {url!r}. Available: {sorted(_MACROS)}")
    query = urllib.parse.quote_plus(kwargs.get("query", ""))
    return template.format(query=query)


async def fetch_browser_ws_url(port: int) -> str:
    """Browser-level CDP endpoint. Unlike a page endpoint it survives tabs
    opening and closing, and it is the only place Target.createTarget works."""
    import urllib.request
    import time

    def _do_fetch() -> dict:
        with urllib.request.urlopen(
            f"http://localhost:{port}/json/version", timeout=2
        ) as resp:
            return json.loads(resp.read())

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            info = await asyncio.to_thread(_do_fetch)
            if ws_url := info.get("webSocketDebuggerUrl"):
                return ws_url
        except Exception:
            pass
        await asyncio.sleep(0.2)
    raise RuntimeError(f"No Chrome browser endpoint found on port {port}")


class Browser:
    def __init__(
        self,
        llm: "LLMAdapter | None" = None,
        headless: bool = True,
        safe: bool = False,
        proxy: str | None = None,
        stealth: bool = False,
    ) -> None:
        self._llm = llm
        self._headless = headless
        self._safe = safe
        self._proxy = proxy
        self._stealth = stealth
        self._launcher: ChromeLauncher | None = None
        self._engine: CDPEngine | None = None
        self._port: int = 0
        self._pages: list[Page] = []
        self.trace = Trace()

    async def __aenter__(self) -> "Browser":
        await self._connect()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    async def _connect(self) -> None:
        if self._engine:
            return
        self._launcher = ChromeLauncher()
        self._port = self._launcher.launch(
            headless=self._headless, proxy=self._proxy, stealth=self._stealth
        )
        ws_url = await fetch_browser_ws_url(self._port)
        self._engine = CDPEngine()
        await self._engine.connect(ws_url)

    async def open(self, url: str, **kwargs: str) -> Page:
        """Open a URL in its own tab and return a Page bound to it.

        Every call gets an independent tab with its own CDP connection, so pages
        can be driven concurrently:

            pages = await asyncio.gather(*(browser.open(u) for u in urls))

        ponytail: no built-in concurrency limit — wrap in an asyncio.Semaphore if
        you need one. Chrome starts degrading somewhere past a few dozen live tabs,
        and the right ceiling depends on the machine, not on grip.
        """
        await self._connect()
        assert self._engine is not None

        url = _expand_macro(url, **kwargs)

        if not url.startswith(("http", "about:", "data:", "file:", "blob:")):
            url = "https://" + url

        result = await self._engine.send("Target.createTarget", {"url": "about:blank"})
        target_id = result["targetId"]

        page_engine = CDPEngine()
        await page_engine.connect(
            f"ws://localhost:{self._port}/devtools/page/{target_id}"
        )
        page = Page(
            engine=page_engine,
            trace=self.trace,
            target_id=target_id,
            safe=self._safe,
            closer=self._close_target,
        )
        self._pages.append(page)
        try:
            await page.goto(url)
        except BaseException:
            # If goto() fails — or the caller cancels us mid-navigate, which is what
            # asyncio.wait_for() around open() does on timeout — this coroutine never
            # returns, so the caller has no Page to close. The tab and its websocket
            # would then stay open for the lifetime of the Browser. Cancellation is a
            # BaseException, so `except Exception` would miss the common case.
            # Shielded so the cleanup completes even while we are being cancelled.
            with contextlib.suppress(Exception):
                await asyncio.shield(asyncio.ensure_future(page.close()))
            raise
        return page

    async def _close_target(self, target_id: str) -> None:
        if self._engine:
            await self._engine.send("Target.closeTarget", {"targetId": target_id})
        self._pages = [p for p in self._pages if p._target_id != target_id]

    async def run(self, goal: str, url: str) -> "RunResult":
        from grip.runner import Runner
        page = await self.open(url)
        runner = Runner(llm=self._llm, page=page, trace=self.trace)
        return await runner.run(goal)

    async def close(self) -> None:
        for page in list(self._pages):
            try:
                await page.close()
            except Exception:
                logger.debug("Failed to close tab %s", page._target_id, exc_info=True)
        self._pages.clear()
        if self._engine:
            await self._engine.disconnect()
            self._engine = None
        if self._launcher:
            self._launcher.terminate()
            self._launcher = None

    async def save_session(self, path: str) -> None:
        if not self._engine:
            raise RuntimeError("Browser is not connected. Use open() or async with first.")
        # Storage, not Network: the browser-level endpoint has no Network domain,
        # and Storage.getCookies returns every cookie rather than only the ones
        # scoped to one tab.
        result = await self._engine.send("Storage.getCookies", {})
        cookies = result.get("cookies", [])
        with open(path, "w") as f:
            json.dump(cookies, f, indent=2)

    async def load_session(self, path: str) -> None:
        if not self._engine:
            raise RuntimeError("Browser is not connected. Use open() or async with first.")
        try:
            with open(path) as f:
                cookies = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Session file not found: {path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Session file is not valid JSON: {path}") from e
        await self._engine.send("Storage.setCookies", {"cookies": cookies})
