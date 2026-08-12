"""
Concurrent page fetch — the primitive retrieval is built on.
Run: .venv/bin/python -m pytest tests/integration/test_concurrent_pages.py -v -s
"""
import asyncio
import atexit
import pathlib
import shutil
import tempfile
import uuid

import pytest

from grip.browser import Browser

# data: is refused by the navigation policy (attacker-controlled markup in page
# context); a real file on disk gives each tab a distinct URL just as well.
_FIXTURE_DIR = tempfile.mkdtemp(prefix="grip_fixtures_")
atexit.register(shutil.rmtree, _FIXTURE_DIR, True)


def _page_url(marker: str) -> str:
    path = pathlib.Path(_FIXTURE_DIR) / f"{marker}_{uuid.uuid4().hex}.html"
    path.write_text(
        f"<html><head><title>{marker}</title></head><body><h1>{marker}</h1></body></html>"
    )
    return path.as_uri()


@pytest.mark.asyncio
async def test_concurrent_pages_are_independent():
    """Before this, Browser held one tab and the second open() clobbered the first."""
    markers = ["alpha", "bravo", "charlie", "delta"]
    async with Browser(headless=True, allow_file=True) as browser:
        pages = await asyncio.gather(*(browser.open(_page_url(m)) for m in markers))
        snapshots = await asyncio.gather(*(p.snapshot() for p in pages))

        for marker, snap in zip(markers, snapshots):
            assert marker in snap.text_content, (
                f"page for {marker!r} saw {snap.text_content!r} — tabs are sharing state"
            )

        assert len({s.url for s in snapshots}) == len(markers)


@pytest.mark.asyncio
async def test_pages_stay_independent_after_later_opens():
    """The original bug: opening a second page changed what the first one saw."""
    async with Browser(headless=True, allow_file=True) as browser:
        first = await browser.open(_page_url("first"))
        await browser.open(_page_url("second"))
        snap = await first.snapshot()
        assert "first" in snap.text_content
        assert "second" not in snap.text_content


async def _target_ids(browser) -> set[str]:
    result = await browser._engine.send("Target.getTargets", {})
    return {t["targetId"] for t in result["targetInfos"] if t["type"] == "page"}


@pytest.mark.asyncio
async def test_close_releases_the_tab():
    async with Browser(headless=True, allow_file=True) as browser:
        page = await browser.open(_page_url("closeme"))
        target_id = page._target_id
        assert target_id in await _target_ids(browser)

        await page.close()
        await page.close()  # idempotent

        # Target.closeTarget returns once close is *initiated*, so poll rather
        # than assert on the tab list immediately.
        for _ in range(50):
            if target_id not in await _target_ids(browser):
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail(f"tab {target_id} still open 5s after close()")

        assert browser._pages == []


async def _webdriver_and_ua(browser) -> tuple[bool, str]:
    page = await browser.open("about:blank")
    r = await page._engine.send(
        "Runtime.evaluate",
        {
            "expression": "JSON.stringify([navigator.webdriver, navigator.userAgent])",
            "returnByValue": True,
        },
    )
    import json as _json

    webdriver, ua = _json.loads(r["result"]["value"])
    return webdriver, ua


@pytest.mark.asyncio
async def test_stealth_changes_the_two_free_tells():
    """grip is a general SDK — masking automation must be an explicit choice.

    navigator.webdriver's *default* value (true/false) is a Chrome-build
    fact, not something this test can pin: the machine that wrote it may
    resolve a pinned Chrome for Testing via _CACHED_CHROME_GLOBS, CI resolves
    whatever `google-chrome` is on PATH, and
    --disable-blink-features=AutomationControlled has no stable cross-version
    effect on that flag. So this only asserts stealth *changes* webdriver
    relative to the non-stealth baseline captured in the same run, plus the
    one thing that is deterministic: the UA string.
    """
    async with Browser(headless=True, allow_file=True) as baseline_browser:
        baseline_webdriver, baseline_ua = await _webdriver_and_ua(baseline_browser)

    async with Browser(headless=True, stealth=True, allow_file=True) as stealth_browser:
        stealth_webdriver, stealth_ua = await _webdriver_and_ua(stealth_browser)

    assert stealth_webdriver != baseline_webdriver, (
        f"stealth=True did not change navigator.webdriver (stayed {stealth_webdriver!r})"
    )
    # stealth derives its UA from the real running Chrome (Browser._resolve_stealth_ua)
    # rather than a hardcoded version string — pinning this test to the literal
    # _STEALTH_UA fallback would make it pass even if that derivation broke and
    # silently fell back. Assert the actual, version-independent invariant instead:
    # same UA as baseline except "HeadlessChrome" swapped for "Chrome".
    assert stealth_ua == baseline_ua.replace("HeadlessChrome/", "Chrome/")
    assert "Headless" not in stealth_ua


@pytest.mark.asyncio
async def test_stealth_ua_changes_the_outgoing_header_not_just_navigator_ua():
    """Network.setUserAgentOverride is documented to affect both the
    JS-visible navigator.userAgent AND the outgoing User-Agent request
    header — every other assertion in this file only ever checked the JS
    side. A request header still saying HeadlessChrome while JS claims
    Chrome would be a worse, trivially server-side-detectable regression
    from this change, not a fix — this is the one test that would catch it.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen_headers: dict[str, str] = {}

    class _Echo(BaseHTTPRequestHandler):
        def do_GET(self):
            seen_headers.update(dict(self.headers))
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/"
        async with Browser(headless=True, stealth=True, allow_private=True) as browser:
            await browser.open(url)
    finally:
        httpd.shutdown()

    ua_header = seen_headers.get("User-Agent", "")
    assert ua_header, "the request never reached the local server"
    assert "Headless" not in ua_header, (
        f"outgoing User-Agent header still says Headless: {ua_header!r}"
    )


@pytest.mark.asyncio
async def test_cancelled_open_does_not_leak_a_tab():
    """asyncio.wait_for() around open() cancels it mid-navigate on timeout. The
    caller never receives a Page, so Browser.open() must clean up after itself or
    the tab and its websocket leak for the lifetime of the Browser."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    stop = threading.Event()

    class _Slow(BaseHTTPRequestHandler):
        def do_GET(self):
            stop.wait(timeout=20)  # never finishes before the caller gives up
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), _Slow)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/"

    try:
        # a loopback server: private ranges are refused unless opted into
        async with Browser(headless=True, allow_private=True) as browser:
            before = await _target_ids(browser)
            with pytest.raises((TimeoutError, asyncio.TimeoutError)):
                await asyncio.wait_for(browser.open(url), timeout=2.0)

            assert browser._pages == [], "Page left in the registry after a failed open"

            for _ in range(50):
                if await _target_ids(browser) == before:
                    break
                await asyncio.sleep(0.1)
            else:
                pytest.fail("tab leaked after a cancelled open()")
    finally:
        stop.set()
        httpd.shutdown()
