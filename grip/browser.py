from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import urllib.parse
from typing import TYPE_CHECKING, Self

from grip.cdp.engine import CDPEngine
from grip.cdp.launcher import ChromeLauncher
from grip.page import Page
from grip.security.policy import NavigationPolicy
from grip.trace import Trace

if TYPE_CHECKING:
    from grip.adapters.base import LLMAdapter
    from grip.runner import RunResult

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
    import time
    import urllib.request

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
        except Exception:  # noqa: BLE001, S110 — best-effort probe, retried until deadline below
            pass
        await asyncio.sleep(0.2)
    raise RuntimeError(f"No Chrome browser endpoint found on port {port}")


class Browser:
    def __init__(
        self,
        llm: LLMAdapter | None = None,
        headless: bool = True,
        safe: bool = False,
        proxy: str | None = None,
        stealth: bool = False,
        block_resources: bool = False,
        allow_private: bool = False,
        allow_file: bool = False,
        user_data_dir: str | None = None,
        cdp_url: str | None = None,
    ) -> None:
        self._llm = llm
        self._headless = headless
        self._safe = safe
        self._proxy = proxy
        self._stealth = stealth
        self._block_resources = block_resources
        self._policy = NavigationPolicy(
            allow_private=allow_private, allow_file=allow_file
        )
        self._user_data_dir = user_data_dir
        self._cdp_url = cdp_url
        self._launcher: ChromeLauncher | None = None
        self._engine: CDPEngine | None = None
        self._port: int = 0
        self._pages: list[Page] = []
        # open() is documented for concurrent use (asyncio.gather over URLs). Without
        # this, N first-callers each see _engine as None and each launch their own
        # Chrome — N-1 of which nothing owns and nothing terminates.
        self._connect_lock = asyncio.Lock()
        self.trace = Trace()

    async def __aenter__(self) -> Self:
        await self._connect()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    async def _connect(self) -> None:
        if self._engine:
            return
        async with self._connect_lock:
            if self._engine:
                return
            if self._cdp_url:
                # Attaching to a Chrome someone else launched — or a remote CDP
                # engine entirely. No profile, no process, nothing to terminate.
                engine = CDPEngine()
                await engine.connect(self._cdp_url)
                self._engine = engine
                return
            launcher = ChromeLauncher(user_data_dir=self._user_data_dir)
            # launch() polls for the DevTools port for up to 10s; on the loop that
            # stalls every other tab.
            await asyncio.to_thread(
                launcher.launch,
                headless=self._headless,
                proxy=self._proxy,
                stealth=self._stealth,
            )
            # Chrome is already running by this point, so any failure between here
            # and a live engine has to clean it up: __aenter__ raising means
            # __aexit__ never runs and close() is never called.
            try:
                self._port = launcher.port
                ws_url = await fetch_browser_ws_url(self._port)
                engine = CDPEngine()
                await engine.connect(ws_url)
            except BaseException:
                launcher.terminate()
                raise
            self._launcher = launcher
            self._engine = engine

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
            # Bare domains still work; everything else reaches the policy as-is so
            # a non-http scheme cannot be laundered into an allowed one.
            url = "https://" + url

        if reason := self._policy.check(url):
            raise ValueError(f"navigation refused: {reason}")

        result = await self._engine.send("Target.createTarget", {"url": "about:blank"})
        target_id = result["targetId"]

        page_engine = CDPEngine()
        await page_engine.connect(self._page_ws_url(target_id))
        page = Page(
            engine=page_engine,
            trace=self.trace,
            target_id=target_id,
            safe=self._safe,
            closer=self._close_target,
            block_resources=self._block_resources,
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

    def _page_ws_url(self, target_id: str) -> str:
        """Websocket for one tab.

        Derived from cdp_url when attached, because the endpoint may be anywhere:
        a remote CDP engine is a wss:// host on the public internet, often with an
        auth token in the query string. Both have to survive the rewrite — assuming
        ws://localhost here is what confines grip to a Chrome on this machine.
        """
        if self._cdp_url:
            parts = urllib.parse.urlsplit(self._cdp_url)
            return urllib.parse.urlunsplit(
                (parts.scheme, parts.netloc, f"/devtools/page/{target_id}", parts.query, "")
            )
        return f"ws://localhost:{self._port}/devtools/page/{target_id}"

    async def _close_target(self, target_id: str) -> None:
        if self._engine:
            await self._engine.send("Target.closeTarget", {"targetId": target_id})
        self._pages = [p for p in self._pages if p._target_id != target_id]

    async def run(self, goal: str, url: str) -> RunResult:
        from grip.runner import Runner
        assert self._llm is not None, "Browser.run() requires an llm adapter"
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
        try:
            if self._engine:
                await self._engine.disconnect()
        except Exception:
            # Teardown never raises: an already-dead socket is not a caller error,
            # and raising here would mask whatever exception is unwinding __aexit__.
            logger.debug("Failed to disconnect the browser engine", exc_info=True)
        finally:
            self._engine = None
            # Whatever the websocket did, the OS process and its temp profile are
            # ours to reclaim. Skipping this is how orphaned Chromes accumulate.
            if self._launcher:
                await self._launcher.aterminate()
                self._launcher = None

    async def save_session(self, path: str) -> None:
        if not self._engine:
            raise RuntimeError("Browser is not connected. Use open() or async with first.")
        # Storage, not Network: the browser-level endpoint has no Network domain,
        # and Storage.getCookies returns every cookie rather than only the ones
        # scoped to one tab.
        result = await self._engine.send("Storage.getCookies", {})
        cookies = result.get("cookies", [])

        def _write() -> None:
            with open(path, "w") as f:
                json.dump(cookies, f, indent=2)

        await asyncio.to_thread(_write)

    async def load_session(self, path: str) -> None:
        if not self._engine:
            raise RuntimeError("Browser is not connected. Use open() or async with first.")

        def _read() -> list[dict]:
            with open(path) as f:
                return json.load(f)

        try:
            cookies = await asyncio.to_thread(_read)
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Session file not found: {path}") from e
        except json.JSONDecodeError as e:
            raise ValueError(f"Session file is not valid JSON: {path}") from e
        await self._engine.send("Storage.setCookies", {"cookies": cookies})
