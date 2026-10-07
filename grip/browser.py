from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import subprocess
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
        self._owned_shutdown_process: subprocess.Popen[bytes] | None = None
        self._owned_cleanup_task: asyncio.Task[None] | None = None
        self._engine: CDPEngine | None = None
        self._remote_setup_incomplete = False
        self._port: int = 0
        self._pages: list[Page] = []
        # open() is documented for concurrent use (asyncio.gather over URLs). Without
        # this, N first-callers each see _engine as None and each launch their own
        # Chrome — N-1 of which nothing owns and nothing terminates.
        self._connect_lock = asyncio.Lock()
        self._popup_attach_lock = asyncio.Lock()
        self._popup_attach_armed = False
        self._popup_chrome_terminated = False
        self._popup_tasks: set[asyncio.Task[None]] = set()
        self._popup_owners: dict[str, Page] = {}
        self.trace = Trace()

    async def __aenter__(self) -> Self:
        await self._connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def _connect(self) -> None:
        if self._engine and not self._remote_setup_incomplete:
            return
        async with self._connect_lock:
            if self._engine:
                if self._remote_setup_incomplete:
                    raise RuntimeError("Remote connection setup failed. Close before reconnecting.")
                return
            if self._cdp_url:
                # Attaching to a Chrome someone else launched — or a remote CDP
                # engine entirely. No profile, no process, nothing to terminate.
                engine = CDPEngine()
                try:
                    await engine.connect(self._cdp_url)
                    await self._apply_permissions(engine)
                    await self._resolve_stealth_ua(engine)
                except BaseException:
                    # __aenter__ failure never reaches __aexit__. Release our
                    # socket now; if release fails, retain explicit retry ownership.
                    self._engine = engine
                    self._remote_setup_incomplete = True
                    cleanup = asyncio.create_task(engine.disconnect())
                    while not cleanup.done():
                        try:
                            await asyncio.wait({cleanup})
                        except asyncio.CancelledError:
                            continue
                    if not cleanup.cancelled() and cleanup.exception() is None:
                        self._engine = None
                        self._remote_setup_incomplete = False
                    raise
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
            self._popup_chrome_terminated = False
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

        await self._ensure_popup_routing()

        # Cancellation must not discard the only authoritative identity of a
        # tab Chrome has created. Finish this one command, then register and
        # close its exact target before propagating caller cancellation.
        creation = asyncio.create_task(self._engine.send(
            "Target.createTarget", {"url": "about:blank"},
        ))
        creation_cancelled: asyncio.CancelledError | None = None
        while True:
            try:
                await asyncio.wait({creation})
                result = creation.result()
                break
            except asyncio.CancelledError as exc:
                if creation.cancelled():
                    raise
                creation_cancelled = exc
            except Exception as exc:
                if creation_cancelled is not None:
                    raise creation_cancelled from exc
                raise
        target_id = result["targetId"]

        page_engine = CDPEngine()
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
        self._popup_owners[target_id] = page
        try:
            if creation_cancelled is not None:
                raise creation_cancelled
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
            await page.goto(url)
        except BaseException:
            # No Page reaches the caller on failure. Keep its guards connected
            # until target absence is verified, including under repeated cancel.
            cleanup = asyncio.create_task(page.close())
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not cleanup.cancelled() and cleanup.exception() is not None:
                logger.debug("Failed to close incomplete tab %s", target_id,
                             exc_info=cleanup.exception())
            raise
        return page

    async def _ensure_popup_routing(self) -> None:
        async with self._popup_attach_lock:
            if self._popup_attach_armed:
                return
            assert self._engine is not None
            self._engine.on("Target.attachedToTarget", self._on_page_target_attached)
            try:
                await self._engine.send("Target.setAutoAttach", {
                    "autoAttach": True, "waitForDebuggerOnStart": True,
                    "flatten": True, "filter": [{"type": "page", "exclude": False}],
                })
            except BaseException:
                self._engine.off("Target.attachedToTarget", self._on_page_target_attached)
                raise
            self._popup_attach_armed = True

    def _on_page_target_attached(self, params: dict[str, Any]) -> None:
        assert self._engine is not None
        info = params.get("targetInfo", {})
        # Retain opener ownership until Browser teardown: an attach queued just
        # after its Page closes still belongs to that Page's popup policy.
        opener = self._popup_owners.get(info.get("openerId", ""))
        if opener is not None:
            if info.get("targetId"):
                self._popup_owners[info["targetId"]] = opener
            before = set(opener._bg_tasks)
            opener._on_target_attached(params, popup_engine=self._engine)
            for task in opener._bg_tasks - before:
                self._popup_tasks.add(task)
                task.add_done_callback(self._popup_tasks.discard)
            return
        # Browser-created blank tabs and unrelated remote tabs are not popups
        # owned by a managed Page. Never leave them waiting for a debugger.
        task = asyncio.create_task(self._resume_unmanaged_target(params.get("sessionId", "")))
        self._popup_tasks.add(task)
        task.add_done_callback(self._popup_tasks.discard)

    async def _resume_unmanaged_target(self, session_id: str) -> None:
        assert self._engine is not None
        with contextlib.suppress(Exception):
            await self._engine.send("Runtime.runIfWaitingForDebugger", {}, session_id=session_id)

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
        if not self._popup_chrome_terminated:
            if self._engine is None:
                raise RuntimeError("Cannot verify target closure without browser connection.")
            # A retry may find that a cancelled previous closer already closed
            # the target. Inventory still proves absence in that case.
            async with asyncio.timeout(2.0):
                with contextlib.suppress(Exception):
                    await self._engine.send("Target.closeTarget", {"targetId": target_id})
                while True:
                    inventory = await self._engine.send("Target.getTargets")
                    targets = inventory.get("targetInfos")
                    if not isinstance(targets, list) or any(
                        not isinstance(info, dict)
                        or not isinstance(info.get("targetId"), str)
                        or not info["targetId"] for info in targets
                    ):
                        raise RuntimeError("Cannot verify managed target absence.")
                    if not any(info["targetId"] == target_id for info in targets):
                        break
                    await asyncio.sleep(0.01)
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

    async def _resolve_unclosed_popups(self) -> None:
        if self._popup_chrome_terminated:
            for page in self._popup_owners.values():
                page._unclosed_popup_targets.clear()
            return
        unresolved = [p for p in self._popup_owners.values() if p._unclosed_popup_targets]
        if unresolved:
            if self._launcher is not None:
                # Detaching would release a surviving child's debugger pause.
                # Our Chrome must be gone before any socket is disconnected.
                await self._shutdown_owned_chrome(graceful=False)
                for page in unresolved:
                    page._unclosed_popup_targets.clear()
            else:
                assert self._engine is not None
                for page in set(unresolved):
                    if any(
                        target in page._popup_frame_targets
                        and page._popup_guard_engines.get(target) is page._engine
                        for target in page._unclosed_popup_targets
                    ):
                        # Main-frame child sessions belong to the Page socket.
                        # Closing its verified owner destroys every such frame
                        # while that socket's Fetch guard remains connected.
                        await page.close()
                    for target_id, session_id in tuple(page._unclosed_popup_targets.items()):
                        origin = page._popup_guard_engines.get(target_id, self._engine)
                        await page._close_popup_target(target_id, origin, session_id)
                if any(p._unclosed_popup_targets for p in unresolved):
                    raise RuntimeError("Cannot detach: blocked popup closure is unverified.")

    async def _shutdown_owned_chrome(self, *, graceful: bool = True) -> None:
        launcher = self._launcher
        if launcher is None:
            return
        process = self._owned_shutdown_process or getattr(launcher, "_process", None)
        # Launcher cleanup mutates its process property, even after a cancelled
        # caller stops awaiting its worker thread. Retain independent evidence.
        self._owned_shutdown_process = process
        if self._owned_cleanup_task is not None:
            cleanup = self._owned_cleanup_task
            try:
                await asyncio.shield(cleanup)
            finally:
                if cleanup.done():
                    self._owned_cleanup_task = None
        if process is not None and getattr(launcher, "_process", None) is None:
            launcher._process = process
        if (
            graceful and self._engine is not None and process is not None
            and process.poll() is None
        ):
            # Native shutdown flushes persistent profile stores. Keep guards
            # attached while Chrome closes its targets and exits.
            with contextlib.suppress(Exception):
                await self._engine.send("Browser.close", timeout=2.0)
            try:
                await asyncio.to_thread(process.wait, timeout=5.0)
            except subprocess.TimeoutExpired:
                logger.debug("Native Chrome shutdown timed out; terminating owned process")
        cleanup = asyncio.create_task(launcher.aterminate())
        self._owned_cleanup_task = cleanup
        try:
            await asyncio.shield(cleanup)
        finally:
            if cleanup.done():
                self._owned_cleanup_task = None
        if process is not None and process.poll() is None:
            # The launcher cleanup normally reaps the process. Do not release
            # guards if termination failed, and retain ownership for a retry.
            launcher._process = process
            raise RuntimeError("Owned Chrome remains alive; security guards retained.")
        self._launcher = None
        self._owned_shutdown_process = None
        self._popup_chrome_terminated = True

    async def close(self) -> None:
        if self._remote_setup_incomplete and self._engine is not None:
            # No targets were created during incomplete setup. A failed retry
            # must keep ownership, rather than the normal teardown's best effort.
            await self._engine.disconnect()
            self._engine = None
            self._remote_setup_incomplete = False
            return
        # Popup closures must finish before disabling auto-attach can release
        # their debugger pause. Guarded closures also keep the opener alive.
        if self._popup_tasks:
            await asyncio.shield(asyncio.gather(*self._popup_tasks, return_exceptions=True))
        if self._engine:
            for page in set(self._popup_owners.values()):
                await asyncio.shield(page._close_guarded_popups(self._engine))
        await self._resolve_unclosed_popups()
        for page in dict.fromkeys([*self._pages, *self._popup_owners.values()]):
            try:
                await page.close()
            except Exception:
                logger.debug("Failed to close tab %s", page._target_id, exc_info=True)
        # An attach delivered while an opener closes retains its owner and
        # must complete its guarded closure before any session is detached.
        while self._popup_tasks:
            await asyncio.shield(asyncio.gather(*self._popup_tasks, return_exceptions=True))
        # Flush queued attachment events before the final closure check.
        if self._engine and self._popup_attach_armed and not self._popup_chrome_terminated:
            try:
                targets = await self._engine.send("Target.getTargets", {}, timeout=2.0)
            except Exception:
                if self._launcher is None:
                    raise
                # A dead transport cannot prove target absence. Owned process
                # death can, and must precede detaching any page guard socket.
                await self._shutdown_owned_chrome(graceful=False)
                targets = {"targetInfos": []}
            while self._popup_tasks:
                await asyncio.shield(asyncio.gather(*self._popup_tasks, return_exceptions=True))
            target_infos = targets.get("targetInfos")
            if self._launcher is None and (
                not isinstance(target_infos, list)
                or any(
                    not isinstance(info, dict)
                    or not isinstance(info.get("targetId"), str)
                    or not info["targetId"]
                    for info in target_infos
                )
            ):
                raise RuntimeError("Cannot detach: managed target absence is unverified.")
            if self._launcher is None and any(
                info.get("targetId") in self._popup_owners
                or (
                    info.get("openerId") in self._popup_owners
                )
                for info in target_infos or []
            ):
                raise RuntimeError("Cannot detach: managed popup opener or child still exists.")
        await self._resolve_unclosed_popups()
        if self._launcher is not None:
            # End the owned process before releasing debugger pauses. A remote
            # browser instead requires all owned openers/blocked children gone.
            await self._shutdown_owned_chrome()
        if self._popup_chrome_terminated:
            for page in dict.fromkeys([*self._pages, *self._popup_owners.values()]):
                await page.close()
        self._pages.clear()
        if self._engine and self._popup_attach_armed:
            if not self._popup_chrome_terminated:
                with contextlib.suppress(Exception):
                    await self._engine.send("Target.setAutoAttach", {
                        "autoAttach": False, "waitForDebuggerOnStart": False, "flatten": True,
                    })
            while self._popup_tasks:
                await asyncio.shield(asyncio.gather(*self._popup_tasks, return_exceptions=True))
            await self._resolve_unclosed_popups()
            self._engine.off("Target.attachedToTarget", self._on_page_target_attached)
            self._popup_attach_armed = False
        if self._popup_tasks:
            await asyncio.shield(asyncio.gather(*self._popup_tasks, return_exceptions=True))
        self._popup_tasks.clear()
        self._popup_owners.clear()
        try:
            if self._engine:
                await self._engine.disconnect()
        except Exception:
            # Teardown never raises: an already-dead socket is not a caller error,
            # and raising here would mask whatever exception is unwinding __aexit__.
            logger.debug("Failed to disconnect the browser engine", exc_info=True)
        finally:
            self._engine = None
            self._remote_setup_incomplete = False
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
