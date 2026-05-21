"""
Real Chrome integration tests for click, type, press, extract, multi-nav, error paths.
Injects HTML into about:blank so no network needed — deterministic, fast.
"""
import asyncio
import json
import pytest
from grip.browser import Browser
from grip.errors.types import GripError, ErrorType


# ── helpers ──────────────────────────────────────────────────────────────────

async def open_with_html(browser: Browser, html: str):
    """Navigate to about:blank then inject HTML via document.write()."""
    page = await browser.open("about:blank")
    await browser._engine.send(
        "Runtime.evaluate",
        {
            "expression": f"document.open('text/html','replace');document.write({json.dumps(html)});document.close();",
            "returnByValue": True,
        },
    )
    await asyncio.sleep(0.15)  # let DOM settle after synchronous write
    return page


CLICK_HTML = """
<html><body>
  <button onclick="document.getElementById('s').textContent='clicked'">Buy Now</button>
  <span id="s">not clicked</span>
</body></html>
"""

FORM_HTML = """
<html><body>
  <input id="q" type="text" placeholder="search here" />
  <button type="submit" onclick="document.getElementById('r').textContent=document.getElementById('q').value">Go</button>
  <div id="r"></div>
</body></html>
"""

SHADOW_HTML = """
<html><body style="margin:0;padding:20px">
  <div id="host" style="display:block"></div>
  <script>
    const host = document.getElementById('host');
    const shadow = host.attachShadow({mode: 'open'});
    shadow.innerHTML = '<button style="display:block;width:120px;height:36px">Shadow Button</button>';
  </script>
</body></html>
"""

CONTENT_HTML = """
<html><body>
  <h1>Product: Blue Sneakers</h1>
  <p>Price: $64.99</p>
  <p>In stock: Yes</p>
</body></html>
"""


# ── click ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_click_real_element():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, CLICK_HTML)
        await page.snapshot()

        await page.click("Buy Now")

        result = await browser._engine.send(
            "Runtime.evaluate",
            {"expression": "document.getElementById('s').textContent", "returnByValue": True},
        )
        value = result.get("result", {}).get("value", "")
        assert value == "clicked", f"Expected 'clicked', got {value!r}"


@pytest.mark.asyncio
async def test_click_raises_on_missing_element():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, CLICK_HTML)
        await page.snapshot()

        with pytest.raises(GripError) as exc_info:
            await page.click("nonexistent element xyz")

        assert exc_info.value.error.type == ErrorType.ELEMENT_NOT_FOUND


# ── type ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_type_real_input():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, FORM_HTML)
        await page.snapshot()

        await page.type("search", "blue sneakers")

        result = await browser._engine.send(
            "Runtime.evaluate",
            {"expression": "document.getElementById('q').value", "returnByValue": True},
        )
        value = result.get("result", {}).get("value", "")
        assert value == "blue sneakers", f"Expected 'blue sneakers', got {value!r}"


@pytest.mark.asyncio
async def test_type_and_click_sequence():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, FORM_HTML)
        await page.snapshot()

        await page.type("search", "grip test")
        await page.click("Go")

        result = await browser._engine.send(
            "Runtime.evaluate",
            {"expression": "document.getElementById('r').textContent", "returnByValue": True},
        )
        value = result.get("result", {}).get("value", "")
        assert value == "grip test", f"Expected 'grip test', got {value!r}"


# ── press ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_press_does_not_raise():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, FORM_HTML)
        await page.snapshot()
        await page.type("search", "hello")
        await page.press("Enter")  # should not raise


# ── extract ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extract_returns_page_content():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, CONTENT_HTML)

        data = await page.extract({"product": "str", "price": "str"})

        assert "product" in data
        assert "price" in data
        assert data["product"] is not None
        assert "Blue Sneakers" in data["product"]
        assert "64.99" in data["price"]


# ── shadow DOM ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_snapshot_detects_shadow_dom_elements():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, SHADOW_HTML)
        snapshot = await page.snapshot()

        shadow_elements = [el for el in snapshot.elements if el.in_shadow_dom]
        assert len(shadow_elements) > 0, "Expected to find elements inside shadow DOM"
        texts = [el.text for el in shadow_elements]
        assert any("Shadow Button" in t for t in texts), f"Shadow button not found: {texts}"


# ── snapshot versioning ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_snapshot_version_increments():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, CLICK_HTML)
        s1 = await page.snapshot()
        s2 = await page.snapshot()
        s3 = await page.snapshot()
        assert s1.version == 1
        assert s2.version == 2
        assert s3.version == 3


@pytest.mark.asyncio
async def test_changed_from_previous_flag():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, CLICK_HTML)
        s1 = await page.snapshot()
        assert s1.changed_from_previous is True   # first snapshot always changed

        s2 = await page.snapshot()
        assert s2.changed_from_previous is False  # nothing changed

        await page.click("Buy Now")
        s3 = await page.snapshot()
        assert s3.changed_from_previous is True   # DOM changed after click


# ── multi-page navigation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_page_navigation():
    async with Browser(headless=True) as browser:
        page1 = await open_with_html(browser, CLICK_HTML)
        snap1 = await page1.snapshot()
        assert "Buy Now" in snap1.text_content or any(
            "Buy Now" in el.text for el in snap1.elements
        )

        page2 = await open_with_html(browser, CONTENT_HTML)
        snap2 = await page2.snapshot()
        assert "Blue Sneakers" in snap2.text_content


# ── trace ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trace_records_all_actions():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, FORM_HTML)
        await page.snapshot()
        await page.type("search", "test")
        await page.click("Go")
        await page.screenshot()

        actions = [e.action for e in browser.trace.actions]
        assert "snapshot" in actions
        assert "type" in actions
        assert "click" in actions
        assert "screenshot" in actions
        assert browser.trace.total_tokens > 0
