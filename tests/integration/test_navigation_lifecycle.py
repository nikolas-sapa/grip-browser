"""Document identity and failed-open cleanup against real Chrome."""
import asyncio

import pytest

from grip.browser import Browser
from grip.errors import GripError
from grip.errors.types import ErrorType


@pytest.mark.asyncio
@pytest.mark.parametrize("navigation", ["navigate", "reload"])
async def test_same_url_full_navigation_retires_refs(tmp_path, navigation):
    fixture = tmp_path / "document.html"
    fixture.write_text("<button onclick='document.title=\"clicked\"'>Original</button>")
    async with Browser(headless=True, allow_file=True) as browser:
        page = await browser.open(fixture.as_uri())
        before = await page.snapshot()
        old = next(e.ref for e in before.elements if e.tag == "button")
        fixture.write_text("<button onclick='document.title=\"clicked\"'>Replacement</button>")
        committed = asyncio.Event()
        page._engine.on("Page.loadEventFired", lambda _: committed.set())
        if navigation == "navigate":
            await page._engine.send("Page.navigate", {"url": fixture.as_uri()})
        else:
            await page._engine.send("Page.reload")
        await asyncio.wait_for(committed.wait(), 3)
        after = await page.snapshot()
        assert not ({e.ref for e in before.elements} & {e.ref for e in after.elements})
        with pytest.raises(GripError) as stale:
            await page.click(old)
        assert stale.value.error.type == ErrorType.STALE_REF
        title = await page._engine.send("Runtime.evaluate", {
            "expression": "document.title", "returnByValue": True,
        })
        assert title["result"]["value"] != "clicked"


@pytest.mark.asyncio
async def test_same_document_navigation_preserves_ref(tmp_path):
    fixture = tmp_path / "document.html"
    fixture.write_text("<button>Same document</button>")
    async with Browser(headless=True, allow_file=True) as browser:
        page = await browser.open(fixture.as_uri())
        before = await page.snapshot()
        await page._engine.send("Runtime.evaluate", {"expression": "location.hash='same'"})
        after = await page.snapshot()
        assert next(e.ref for e in before.elements if e.tag == "button") == next(
            e.ref for e in after.elements if e.tag == "button"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["connect", "viewport", "geolocation", "goto"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_failed_open_removes_real_target(monkeypatch, stage, cancel):
    from grip.cdp.engine import CDPEngine
    from grip.page import Page

    async with Browser(headless=True, geolocation={"latitude": 1, "longitude": 2}) as browser:
        anchor = await browser.open("about:blank")
        await anchor.close()
        baseline = await browser._engine.send("Target.getTargets")
        baseline_ids = {t["targetId"] for t in baseline["targetInfos"] if t["type"] == "page"}
        engines = []
        original_connect = CDPEngine.connect
        original_send = CDPEngine.send

        async def connect(engine, *args, **kwargs):
            engines.append(engine)
            await original_connect(engine, *args, **kwargs)
            if stage == "connect":
                raise asyncio.CancelledError() if cancel else RuntimeError("setup failed")

        async def fail(*args, **kwargs):
            raise asyncio.CancelledError() if cancel else RuntimeError("setup failed")

        async def send(engine, method, *args, **kwargs):
            if method == "Emulation.setGeolocationOverride":
                await fail()
            return await original_send(engine, method, *args, **kwargs)

        with monkeypatch.context() as patcher:
            patcher.setattr(CDPEngine, "connect", connect)
            if stage == "viewport":
                patcher.setattr(browser, "_apply_viewport", fail)
            elif stage == "geolocation":
                patcher.setattr(CDPEngine, "send", send)
            elif stage == "goto":
                patcher.setattr(Page, "goto", fail)
            with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
                await browser.open("about:blank")
        inventory = await browser._engine.send("Target.getTargets")
        assert {
            t["targetId"] for t in inventory["targetInfos"] if t["type"] == "page"
        } == baseline_ids
        assert browser.pages == ()
        assert len(engines) == 1
        assert engines[0]._ws is None


@pytest.mark.asyncio
@pytest.mark.parametrize("popup", [False, True])
async def test_owned_close_recovers_dead_root_socket_within_eight_seconds(popup):
    browser = Browser(headless=True, allow_popups=popup)
    page = await browser.open("about:blank")
    if popup:
        await page._engine.send("Runtime.evaluate", {
            "expression": "window.open('about:blank', '_blank')", "userGesture": True,
        })
        await page.wait_for_popup(timeout=2)
        assert len(page._guarded_popup_targets) == 1
    process = browser._launcher._process
    page_engines = [p._engine for p in browser.pages]
    root = browser._engine
    await root.disconnect()
    try:
        await asyncio.wait_for(browser.close(), 8)
        assert process.poll() is not None
        assert root._ws is None
        assert all(engine._ws is None for engine in page_engines)
        await browser.close()
    finally:
        if browser._launcher is not None:
            await browser._launcher.aterminate()
