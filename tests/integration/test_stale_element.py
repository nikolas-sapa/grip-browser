"""The bug class this suite exists for: an action resolving to a different
element than the snapshot showed. Each test mutates the DOM between snapshot and
action in a way that used to shift a positional index silently."""
from __future__ import annotations

import atexit
import pathlib
import shutil
import tempfile
import uuid

import pytest

from grip.browser import Browser
from grip.errors import GripError

# data: URLs are attacker-controlled markup executing in page context, so the
# navigation policy refuses them by default. Fixtures are written to a temp file
# and opened with allow_file=True instead.
_FIXTURE_DIR = tempfile.mkdtemp(prefix="grip_fixtures_")
atexit.register(shutil.rmtree, _FIXTURE_DIR, True)


def _fixture(html: str) -> str:
    path = pathlib.Path(_FIXTURE_DIR) / f"fixture_{uuid.uuid4().hex}.html"
    path.write_text(html)
    return path.as_uri()


@pytest.mark.asyncio
async def test_click_after_dom_insertion_hits_intended_element():
    html = """
    <button id="a" onclick="document.title='A'">Alpha</button>
    <button id="b" onclick="document.title='B'">Beta</button>
    """
    async with Browser(allow_file=True) as browser:
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
    async with Browser(allow_file=True) as browser:
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
    async with Browser(allow_file=True) as browser:
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
    async with Browser(allow_file=True) as browser:
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
async def test_handle_survives_a_control_dropping_out_of_the_candidate_set():
    """Handles are allocated per node, not per position. A control that goes
    hidden keeps its stamp but stops being collected; a positional handle would
    then be reissued to a live element further down and querySelector would
    return the stale hidden node — the decoy hijack this change exists to close.
    """
    html = """
    <button id="decoy" onclick="document.title='DECOY'">Delete</button>
    <button id="real" onclick="document.title='REAL'">Delete</button>
    """
    async with Browser(allow_file=True) as browser:
        page = await browser.open(_fixture(html))
        await page.snapshot()
        await page._engine.send("Runtime.evaluate", {
            "expression": "document.getElementById('decoy').style.opacity = '0'"
        })
        snap = await page.snapshot()
        deletes = [e for e in snap.elements if e.text == "Delete"]
        assert len(deletes) == 1, f"expected only the visible control, got {deletes}"
        await page.click(deletes[0].ref)
        result = await page._engine.send(
            "Runtime.evaluate", {"expression": "document.title", "returnByValue": True}
        )
        assert result["result"]["value"] == "REAL"


@pytest.mark.asyncio
async def test_click_after_navigation_does_not_use_stale_snapshot():
    first = _fixture('<button onclick="document.title=\'OLD\'">OnlyOnFirst</button>')
    second = _fixture('<button onclick="document.title=\'NEW\'">Different</button>')
    async with Browser(allow_file=True) as browser:
        page = await browser.open(first)
        await page.snapshot()
        await page.goto(second)
        with pytest.raises(GripError):
            await page.click("OnlyOnFirst")
