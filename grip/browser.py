from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from grip.cdp.engine import CDPEngine
from grip.cdp.launcher import ChromeLauncher, _STEALTH_UA, default_launch_timeout
from grip.page import Page
from grip.security.policy import NavigationPolicy, enforce as enforce_navigation
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

# A sane, deterministic desktop size. Without this, viewport is whatever Chrome
# happens to default to -- which varies by platform and version -- so anything
# that reads window/viewport dimensions gets a different answer per environment.
_DEFAULT_VIEWPORT: dict[str, Any] = {
    "width": 1280,
    "height": 800,
    "device_scale_factor": 1,
    "mobile": False,
    "touch": False,
}

# A real device UA rather than desktop-Chrome-claiming-to-be-mobile: sites that
# branch on UA (not just viewport width) for their mobile layout need this to
# actually see one.
_MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Mobile Safari/537.36"
)

# notifications/geolocation prompts have no one to answer them in an unattended
# run, so both default to denied rather than left at Chrome's "prompt" -- a
# prompt just stalls the page instead of failing loud or granting silently.
_DEFAULT_PERMISSIONS: dict[str, bool] = {
    "notifications": False,
    "geolocation": False,
}


def _expand_macro(url: str, **kwargs: str) -> str:
    if not url.startswith("@"):
        return url
    template = _MACROS.get(url)
    if not template:
        raise ValueError(f"Unknown macro: {url!r}. Available: {sorted(_MACROS)}")
    query = urllib.parse.quote_plus(kwargs.get("query", ""))
    return template.format(query=query)


async def fetch_browser_ws_url(port: int, timeout: float | None = None) -> str:
    """Browser-level CDP endpoint. Unlike a page endpoint it survives tabs
    opening and closing, and it is the only place Target.createTarget works."""
    import time
    import urllib.request

    def _do_fetch() -> dict[str, Any]:
        with urllib.request.urlopen(
            f"http://localhost:{port}/json/version", timeout=2
        ) as resp:
            parsed: dict[str, Any] = json.loads(resp.read())
            return parsed

    deadline = time.monotonic() + (
        timeout if timeout is not None else default_launch_timeout()
    )
    while time.monotonic() < deadline:
        try:
            info = await asyncio.to_thread(_do_fetch)
            if ws_url := info.get("webSocketDebuggerUrl"):
                return str(ws_url)
        except Exception:  # noqa: S110 — best-effort probe, retried until deadline below
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
        allow_popups: bool = False,
        user_data_dir: str | None = None,
        cdp_url: str | None = None,
        launch_timeout: float | None = None,
        viewport: dict[str, Any] | None = None,
        permissions: dict[str, bool] | None = None,
        geolocation: dict[str, float] | None = None,
    ) -> None:
        self._llm = llm
        self._headless = headless
        self._safe = safe
        self._proxy = proxy
        self._stealth = stealth
        self._block_resources = block_resources
        self._policy = NavigationPolicy(
            allow_private=allow_private, allow_file=allow_file, allow_popups=allow_popups
        )
        self._user_data_dir = user_data_dir
        self._cdp_url = cdp_url
        self._launch_timeout = launch_timeout
        # Merged over the defaults rather than replacing them, so a caller who
        # only wants a mobile size doesn't also have to spell out scale/touch.
        self._viewport: dict[str, Any] = {**_DEFAULT_VIEWPORT, **(viewport or {})}
        self._permissions: dict[str, bool] = {**_DEFAULT_PERMISSIONS, **(permissions or {})}
        # A geolocation override is pointless while the geolocation permission is
        # still denied by default -- navigator.geolocation stays blocked regardless
        # of what the override says. Passing geolocation= implies wanting it to
        # actually work, so it grants the permission too, unless the caller set
        # permissions["geolocation"] explicitly (which still wins either way).
        if geolocation is not None and "geolocation" not in (permissions or {}):
            self._permissions["geolocation"] = True
        self._geolocation = geolocation
        # Resolved in _connect() from Browser.getVersion() once the engine is
        # up, not hardcoded — see the comment on _STEALTH_UA in launcher.py for
        # why a pinned version string goes stale. None until then, and stays
        # None entirely when stealth=False.
        self._stealth_ua: str | None = None
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

    async def __aexit__(self, *args: object) -> None:
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
                await self._apply_permissions(engine)
                await self._resolve_stealth_ua(engine)
                self._engine = engine
                return
            launcher = ChromeLauncher(
                user_data_dir=self._user_data_dir,
                launch_timeout=self._launch_timeout,
            )
            # launch() polls for the DevTools port until launch_timeout; on the
            # loop that stalls every other tab.
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
                ws_url = await fetch_browser_ws_url(
                    self._port, timeout=launcher.launch_timeout
                )
                engine = CDPEngine()
                await engine.connect(ws_url)
                await self._apply_permissions(engine)
                await self._resolve_stealth_ua(engine)
            except BaseException:
                launcher.terminate()
                raise
            self._launcher = launcher
            self._engine = engine

    async def _resolve_stealth_ua(self, engine: CDPEngine) -> None:
        """Derives the stealth-mode UA from whatever Chrome is actually
        running, rather than a hardcoded version string that drifts out of
        sync with it (measured 2026-08-12: a pinned "Chrome/149" next to a
        running 151 binary — see _STEALTH_UA's comment in launcher.py). A
        no-op when stealth=False: _stealth_ua stays None and open() never
        applies an override, so a caller who never asked for stealth sees no
        behavior change at all.

        Best-effort like _apply_permissions above: a remote CDP endpoint
        (attach mode via cdp_url) may not implement Browser.getVersion, and
        that must not block attaching to it — falls back to the hardcoded
        constant rather than leaving stealth half-applied.
        """
        if not self._stealth:
            return
        try:
            info = await engine.send("Browser.getVersion")
            real_ua = info.get("userAgent", "")
            self._stealth_ua = (
                real_ua.replace("HeadlessChrome/", "Chrome/") if real_ua else _STEALTH_UA
            )
        except Exception:
            logger.debug("Failed to resolve real UA for stealth mode", exc_info=True)
            self._stealth_ua = _STEALTH_UA

    async def _apply_permissions(self, engine: CDPEngine) -> None:
        """Grant/deny the configured permissions browser-wide, so a
        notifications/geolocation prompt never sits there waiting for a human
        who isn't coming. Best-effort: a remote CDP endpoint (attach mode via
        cdp_url) may not implement Browser.setPermission at all, and that must
        not block attaching to it."""
        for name, allowed in self._permissions.items():
            try:
                await engine.send(
                    "Browser.setPermission",
                    {
                        "permission": {"name": name},
                        "setting": "granted" if allowed else "denied",
                    },
                )
            except Exception:
                logger.debug("Failed to set permission %r", name, exc_info=True)

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

        enforce_navigation(self._policy, url)

        result = await self._engine.send("Target.createTarget", {"url": "about:blank"})
        target_id = result["targetId"]

        page_engine = CDPEngine()
        await page_engine.connect(self._page_ws_url(target_id))
        # Before goto(), not after: emulation set post-navigation is too late for a
        # page that branches its layout/UA off these on the very first paint.
        await self._apply_viewport(page_engine)
        if self._geolocation:
            await page_engine.send(
                "Emulation.setGeolocationOverride",
                {
                    "latitude": self._geolocation["latitude"],
                    "longitude": self._geolocation["longitude"],
                    "accuracy": self._geolocation.get("accuracy", 1),
                },
            )
        page = Page(
            engine=page_engine,
            trace=self.trace,
            target_id=target_id,
            safe=self._safe,
            closer=self._close_target,
            block_resources=self._block_resources,
            policy=self._policy,
            # Not vp["mobile"]: a mobile-emulating page still opens desktop
            # popups (the mobile UA is set directly on this page's own target
            # by _apply_viewport and is a separate override from stealth's).
            stealth_ua=self._stealth_ua,
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

    async def _apply_viewport(self, engine: CDPEngine) -> None:
        """Deterministic size/DPR on every tab, plus touch and a matching UA when
        emulating mobile — a mobile viewport with a desktop UA still gets served
        the desktop layout by any site that branches on UA rather than width.

        mobile= wins over stealth= when both are set: a caller who explicitly
        asked to emulate a phone gets that UA, not a spoofed desktop one —
        stealth's whole point is not surprising a caller who asked for
        something else. Applied here, before goto() in open(), for the same
        reason CLOSED_SHADOW_PATCH_JS has to be armed before goto(): a page's
        own scripts must never see the unmasked (or wrong) UA even on the
        very first navigation.
        """
        vp = self._viewport
        await engine.send(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": vp["width"],
                "height": vp["height"],
                "deviceScaleFactor": vp["device_scale_factor"],
                "mobile": vp["mobile"],
            },
        )
        await engine.send("Emulation.setTouchEmulationEnabled", {"enabled": vp["touch"]})
        if vp["mobile"]:
            await engine.send("Network.setUserAgentOverride", {"userAgent": _MOBILE_UA})
        elif self._stealth_ua:
            await engine.send("Network.setUserAgentOverride", {"userAgent": self._stealth_ua})

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

    @property
    def pages(self) -> tuple[Page, ...]:
        """Open tabs, oldest first. A snapshot copy — closing/opening tabs
        after reading this does not retroactively change it; call again."""
        return tuple(self._pages)

    def get_page(self, target_id: str) -> Page | None:
        """Look up an open tab by the target_id it was opened with, or None."""
        for page in self._pages:
            if page._target_id == target_id:
                return page
        return None

    async def run(self, goal: str, url: str) -> RunResult:
        from grip.runner import Runner
        if self._llm is None:
            raise RuntimeError("Browser.run() requires an llm adapter")
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

    @staticmethod
    def _origin_of(url: str) -> str | None:
        parts = urllib.parse.urlsplit(url)
        if not parts.scheme or not parts.netloc:
            return None
        return f"{parts.scheme}://{parts.netloc}"

    async def save_session(self, path: str) -> None:
        if not self._engine:
            raise RuntimeError("Browser is not connected. Use open() or async with first.")
        # Storage, not Network: the browser-level endpoint has no Network domain,
        # and Storage.getCookies returns every cookie rather than only the ones
        # scoped to one tab.
        result = await self._engine.send("Storage.getCookies", {})
        cookies = result.get("cookies", [])

        # localStorage has no browser-level endpoint the way cookies do — it
        # only exists inside a renderer bound to one origin, so the only origins
        # we can capture are the ones with a tab open right now. (Confirmed
        # against real Chrome: DOMStorage.setDOMStorageItem/getDOMStorageItems
        # from one tab's session targeting a *different* origin's storageId
        # fails with "Frame not found for the given storage id" — cross-origin
        # access isn't available at all, same-origin or nothing.) A save with
        # no open tabs captures cookies only, same as before this change.
        #
        # sessionStorage is deliberately excluded: it's scoped to one browsing
        # context, not one origin, so there is no origin-keyed slot to restore
        # it into that means anything. IndexedDB is out of scope too — much
        # larger surface, structured-clone semantics, not attempted here.
        origins: dict[str, dict[str, dict[str, str]]] = {}
        for page in self._pages:
            # page._current_url is only populated by snapshot() — forcing one
            # here just to read a URL would be a real side effect (ref-registry
            # reset, a full DOM walk) for a save call. Target.getTargetInfo is
            # the CDP-native way to ask a target its URL without touching the
            # page at all.
            info = await self._engine.send(
                "Target.getTargetInfo", {"targetId": page._target_id}
            )
            origin = self._origin_of(info.get("targetInfo", {}).get("url", ""))
            if origin is None or origin in origins:
                continue
            local = await page._engine.send(
                "Runtime.evaluate",
                {
                    "expression": "JSON.stringify(Object.assign({}, window.localStorage))",
                    "returnByValue": True,
                },
            )
            raw = local.get("result", {}).get("value")
            if not raw:
                continue
            items = json.loads(raw)
            if items:
                origins[origin] = {"localStorage": items}

        def _write() -> None:
            # Cookies (and now localStorage) carry session tokens; never leave
            # them world-readable. O_CREAT's mode applies only to a new inode,
            # and re-saving over an existing 0644 file is the common path —
            # fchmod on the fd we already hold tightens it with no path-race
            # window. O_NOFOLLOW refuses a pre-planted symlink at `path` rather
            # than following it and writing the session blob somewhere else.
            # O_EXCL is deliberately not added: re-saving over an existing
            # session file is the normal, expected path here, not an error.
            fd = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
            )
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"cookies": cookies, "origins": origins}, f, indent=2)

        await asyncio.to_thread(_write)

    async def load_session(self, path: str) -> None:
        if not self._engine:
            raise RuntimeError("Browser is not connected. Use open() or async with first.")

        def _read() -> Any:
            with Path(path).open() as f:
                data: Any = json.load(f)
                return data

        try:
            data = await asyncio.to_thread(_read)
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Session file not found: {path}") from e
        except json.JSONDecodeError as e:
            raise ValueError(f"Session file is not valid JSON: {path}") from e

        # Old session files are a bare cookie list — the shape itself is the
        # version marker, since old files predate any format with a version
        # field to check. New files are a dict with "cookies" and "origins".
        if isinstance(data, list):
            cookies: list[dict[str, Any]] = data
            origins: dict[str, dict[str, dict[str, str]]] = {}
        elif isinstance(data, dict):
            cookies = data.get("cookies", [])
            origins = data.get("origins", {})
        else:
            raise ValueError(
                f"Session file has an unrecognized shape: {path} "
                "(expected a cookie list or a {{cookies, origins}} object)"
            )

        if not isinstance(cookies, list):
            raise ValueError(f"Session file 'cookies' must be a list: {path}")
        if not isinstance(origins, dict):
            raise ValueError(f"Session file 'origins' must be an object: {path}")

        await self._engine.send("Storage.setCookies", {"cookies": cookies})

        for origin, storage in origins.items():
            if not isinstance(storage, dict):
                raise ValueError(
                    f"Session file 'origins[{origin!r}]' must be an object: {path}"
                )
            local_items = storage.get("localStorage", {})
            if not local_items:
                continue
            if not isinstance(local_items, dict):
                raise ValueError(
                    f"Session file 'origins[{origin!r}].localStorage' must be "
                    f"an object: {path}"
                )
            # Restoring localStorage needs a live document at that origin —
            # same constraint as the read side. Reuse an already-open tab at
            # this origin if there is one; otherwise open one just for the
            # restore and close it again, so a failed or successful restore
            # never leaves a tab behind that Browser.pages didn't have before.
            page = None
            for candidate in self._pages:
                info = await self._engine.send(
                    "Target.getTargetInfo", {"targetId": candidate._target_id}
                )
                if self._origin_of(info.get("targetInfo", {}).get("url", "")) == origin:
                    page = candidate
                    break
            opened_here = page is None
            if page is None:
                page = await self.open(origin)
            try:
                expr = "".join(
                    f"window.localStorage.setItem({json.dumps(k)}, {json.dumps(v)});"
                    for k, v in local_items.items()
                )
                await page._engine.send("Runtime.evaluate", {"expression": expr})
            finally:
                if opened_here:
                    await page.close()
