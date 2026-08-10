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


@pytest.mark.asyncio
async def test_stealth_is_off_by_default():
    """grip is a general SDK — masking automation must be an explicit choice."""
    async with Browser(headless=True, allow_file=True) as browser:
        page = await browser.open("about:blank")
        r = await page._engine.send(
            "Runtime.evaluate",
            {"expression": "navigator.webdriver", "returnByValue": True},
        )
        assert r["result"]["value"] is True


@pytest.mark.asyncio
async def test_stealth_removes_the_two_free_tells():
    async with Browser(headless=True, stealth=True, allow_file=True) as browser:
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
        assert webdriver is False
        assert "Headless" not in ua


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
