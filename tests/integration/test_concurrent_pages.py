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


@pytest.mark.asyncio
async def test_close_releases_the_tab():
    async with Browser(headless=True) as browser:
        page = await browser.open(_page_url("closeme"))
        before = await browser._engine.send("Target.getTargets", {})
        await page.close()
        await page.close()  # idempotent
        after = await browser._engine.send("Target.getTargets", {})

        def pages(result):
            return [t for t in result["targetInfos"] if t["type"] == "page"]

        assert len(pages(after)) == len(pages(before)) - 1
        assert browser._pages == []
