"""
Concurrent page fetch — the primitive retrieval is built on.
Run: .venv/bin/python -m pytest tests/integration/test_concurrent_pages.py -v -s
"""
import asyncio
import pytest
from grip.browser import Browser


def _page_url(marker: str) -> str:
    return f"data:text/html,<html><head><title>{marker}</title></head><body><h1>{marker}</h1></body></html>"


@pytest.mark.asyncio
async def test_concurrent_pages_are_independent():
    """Before this, Browser held one tab and the second open() clobbered the first."""
    markers = ["alpha", "bravo", "charlie", "delta"]
    async with Browser(headless=True) as browser:
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
    async with Browser(headless=True) as browser:
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
    async with Browser(headless=True) as browser:
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
    async with Browser(headless=True) as browser:
        page = await browser.open("about:blank")
        r = await page._engine.send(
            "Runtime.evaluate",
            {"expression": "navigator.webdriver", "returnByValue": True},
        )
        assert r["result"]["value"] is True


@pytest.mark.asyncio
async def test_stealth_removes_the_two_free_tells():
    async with Browser(headless=True, stealth=True) as browser:
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
