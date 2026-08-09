"""The bug class this suite exists for: an action resolving to a different
element than the snapshot showed. Each test mutates the DOM between snapshot and
action in a way that used to shift a positional index silently."""
from __future__ import annotations

import pytest

from grip.browser import Browser
from grip.errors import GripError


def _fixture(html: str) -> str:
    import base64
    return "data:text/html;base64," + base64.b64encode(html.encode()).decode()


@pytest.mark.asyncio
async def test_click_after_dom_insertion_hits_intended_element():
    html = """
    <button id="a" onclick="document.title='A'">Alpha</button>
    <button id="b" onclick="document.title='B'">Beta</button>
    """
    async with Browser() as browser:
        page = await browser.open(_fixture(html))
        await page.snapshot()
        await page._engine.send("Runtime.evaluate", {"expression": (
            "document.body.insertAdjacentHTML('afterbegin',"
            "'<button onclick=\\\"document.title=&quot;INJECTED&quot;\\\">Zulu</button>')"
        )})
        await page.click("Beta")
        result = await page._engine.send(
            "Runtime.evaluate", {"expression": "document.title", "returnByValue": True}
        )
        assert result["result"]["value"] == "B"


@pytest.mark.asyncio
async def test_click_raises_when_element_removed_after_snapshot():
    html = '<button onclick="document.title=\'X\'">Gone</button>'
    async with Browser() as browser:
        page = await browser.open(_fixture(html))
        await page.snapshot()
        await page._engine.send("Runtime.evaluate", {
            "expression": "document.querySelector('button').remove()"
        })
        with pytest.raises(GripError):
            await page.click("Gone")


@pytest.mark.asyncio
async def test_type_on_non_typable_target_raises():
    html = '<a href="#" aria-label="Search">Search</a><input placeholder="real">'
    async with Browser() as browser:
        page = await browser.open(_fixture(html))
        snap = await page.snapshot()
        link = next(e for e in snap.elements if e.tag == "a")
        with pytest.raises(GripError):
            await page.type(link.ref, "hello")


@pytest.mark.asyncio
async def test_duplicate_labels_resolve_to_distinct_elements():
    html = """
    <button onclick="document.title='FIRST'">Delete</button>
    <button onclick="document.title='SECOND'">Delete</button>
    """
    async with Browser() as browser:
        page = await browser.open(_fixture(html))
        snap = await page.snapshot()
        deletes = [e for e in snap.elements if e.text == "Delete"]
        assert len({e.ref for e in deletes}) == 2, "duplicate labels collapsed onto one ref"
        await page.click(deletes[1].ref)
        result = await page._engine.send(
            "Runtime.evaluate", {"expression": "document.title", "returnByValue": True}
        )
        assert result["result"]["value"] == "SECOND"


@pytest.mark.asyncio
async def test_click_after_navigation_does_not_use_stale_snapshot():
    first = _fixture('<button onclick="document.title=\'OLD\'">OnlyOnFirst</button>')
    second = _fixture('<button onclick="document.title=\'NEW\'">Different</button>')
    async with Browser() as browser:
        page = await browser.open(first)
        await page.snapshot()
        await page.goto(second)
        with pytest.raises(GripError):
            await page.click("OnlyOnFirst")
