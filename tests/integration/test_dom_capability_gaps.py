"""
Real-behaviour coverage for the four DOM-layer capability gaps closed on the
agent-hardening branch (grip/cdp/shadow.py):

  1. Inner scrollable panes / virtual lists (SCROLL_BOTTOM_JS)
  2. Closed shadow roots (CLOSED_SHADOW_PATCH_JS + gripCollect's walk())
  3. SVG shapes carrying role/aria-label/<title> (gripIsSvgCandidate)
  4. Combobox-shaped triggers (gripComboboxInfo)

Each is exercised against a live headless Chrome via CDP rather than a
string-level check on the JS source, the same way
tests/integration/test_discover_elements_perf_parity.py drives real DOM
behaviour. tests/unit/test_shadow.py carries the string-level regression
tests (function names, field names present in the JS text).
"""
import asyncio
import json

import pytest

from grip.browser import Browser
from grip.cdp.shadow import CLOSED_SHADOW_PATCH_JS, DISCOVER_ELEMENTS_JS, SCROLL_BOTTOM_JS


async def open_with_html(browser: Browser, html: str):
    page = await browser.open("about:blank")
    expr = (
        f"document.open('text/html','replace');"
        f"document.write({json.dumps(html)});document.close();"
    )
    await page._engine.send(
        "Runtime.evaluate", {"expression": expr, "returnByValue": True}
    )
    await asyncio.sleep(0.15)
    return page


async def _eval(page, js: str):
    result = await page._engine.send(
        "Runtime.evaluate", {"expression": js, "returnByValue": True}
    )
    value = result.get("result", {}).get("value")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


async def _discover(page) -> list[dict]:
    return await _eval(page, DISCOVER_ELEMENTS_JS)


# --- 1. Inner scrollable panes -----------------------------------------------

SCROLL_PANE_HTML = """
<html><body style="margin:0">
  <div id="pane" style="height:300px;width:400px;overflow-y:auto;">
    <div style="height:2000px">tall content</div>
  </div>
</body></html>
"""


@pytest.mark.asyncio
async def test_scroll_bottom_steps_the_inner_pane_not_just_the_window():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, SCROLL_PANE_HTML)
        try:
            before = await _eval(page, "document.getElementById('pane').scrollTop")
            assert before == 0
            await _eval(page, SCROLL_BOTTOM_JS)
            after = await _eval(page, "document.getElementById('pane').scrollTop")
            # One clientHeight (300) step, not a jump straight to scrollHeight
            # (2000) — page.py's own plateau loop re-calls this and expects
            # to drive the growth itself.
            assert 0 < after <= 300
            window_y = await _eval(page, "window.scrollY")
            assert window_y == 0  # the window itself never had anything to scroll
        finally:
            await page.close()


@pytest.mark.asyncio
async def test_scroll_bottom_falls_back_to_window_when_nothing_scrollable():
    async with Browser(headless=True) as browser:
        page = await open_with_html(
            browser, "<html><body><p>short page</p></body></html>"
        )
        try:
            outcome = await _eval(page, SCROLL_BOTTOM_JS)
            assert outcome is True
        finally:
            await page.close()


# --- 2. Closed shadow roots ---------------------------------------------------

CLOSED_SHADOW_HTML = """
<html><body>
  <div id="host"></div>
  <script>
    const host = document.getElementById('host');
    const root = host.attachShadow({mode: 'closed'});
    root.innerHTML = '<button style="display:block">Closed Shadow Button</button>';
  </script>
</body></html>
"""


@pytest.mark.asyncio
async def test_closed_shadow_content_invisible_without_the_patch():
    """Documents the gap the patch exists to close: without it installed
    before the page's own script runs, a closed root's content is invisible
    to discovery — no signal at all, not even a marker (see
    CLOSED_SHADOW_PATCH_JS's module comment for why nothing else is possible)."""
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, CLOSED_SHADOW_HTML)
        try:
            rows = await _discover(page)
            assert not any(r.get("text") == "Closed Shadow Button" for r in rows)
        finally:
            await page.close()


@pytest.mark.asyncio
async def test_closed_shadow_content_reachable_once_patch_is_installed_first():
    """Installing CLOSED_SHADOW_PATCH_JS before the page's own script runs
    (in production: CDP Page.addScriptToEvaluateOnNewDocument; here: eval'd
    before document.write, which runs the inline <script> synchronously)
    captures the closed root, and gripCollect's walk() reaches it exactly
    like an open one."""
    async with Browser(headless=True) as browser:
        page = await browser.open("about:blank")
        try:
            await page._engine.send(
                "Runtime.evaluate",
                {"expression": CLOSED_SHADOW_PATCH_JS, "returnByValue": True},
            )
            expr = (
                f"document.open('text/html','replace');"
                f"document.write({json.dumps(CLOSED_SHADOW_HTML)});document.close();"
            )
            await page._engine.send(
                "Runtime.evaluate", {"expression": expr, "returnByValue": True}
            )
            await asyncio.sleep(0.15)
            rows = await _discover(page)
            match = next((r for r in rows if r.get("text") == "Closed Shadow Button"), None)
            assert match is not None
            assert match["tag"] == "button"
            assert match["inShadowDom"] is True
            assert match.get("closedShadowUnreadable") is False
        finally:
            await page.close()


# --- 3. SVG shapes with role/aria-label/<title> -------------------------------

SVG_HTML = """
<html><body>
  <svg aria-label="Close" style="display:block;width:24px;height:24px" viewBox="0 0 24 24">
    <path d="M0 0 L24 24"></path>
  </svg>
  <svg style="display:block;width:24px;height:24px" viewBox="0 0 24 24">
    <title>Menu</title>
    <path d="M0 0 L24 24"></path>
  </svg>
  <svg style="display:block;width:24px;height:24px" viewBox="0 0 24 24">
    <path d="M0 0 L24 24"></path>
  </svg>
</body></html>
"""


@pytest.mark.asyncio
async def test_svg_with_aria_label_or_title_becomes_a_candidate():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, SVG_HTML)
        try:
            rows = await _discover(page)
            texts = {r["text"] for r in rows if r["tag"] == "svg"}
            assert "Close" in texts
            assert "Menu" in texts
        finally:
            await page.close()


@pytest.mark.asyncio
async def test_svg_with_no_role_aria_label_or_title_is_not_a_candidate():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, SVG_HTML)
        try:
            rows = await _discover(page)
            svg_rows = [r for r in rows if r["tag"] == "svg"]
            assert len(svg_rows) == 2  # only the labelled/titled ones, not the bare one
        finally:
            await page.close()


# --- 4. Canvas rect ------------------------------------------------------------

CANVAS_HTML = """
<html><body style="margin:0">
  <canvas width="300" height="150" style="display:block;width:300px;height:150px"></canvas>
</body></html>
"""


@pytest.mark.asyncio
async def test_canvas_row_carries_its_own_rect():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, CANVAS_HTML)
        try:
            rows = await _discover(page)
            canvas = next(r for r in rows if r["tag"] == "canvas")
            assert canvas["canvasWidth"] == 300
            assert canvas["canvasHeight"] == 150
        finally:
            await page.close()


@pytest.mark.asyncio
async def test_non_canvas_rows_have_no_rect():
    async with Browser(headless=True) as browser:
        page = await open_with_html(
            browser, "<html><body><button>Click</button></body></html>"
        )
        try:
            rows = await _discover(page)
            button = next(r for r in rows if r["tag"] == "button")
            assert button["canvasWidth"] is None
            assert button["canvasHeight"] is None
        finally:
            await page.close()


# --- 5. Combobox-shaped triggers ------------------------------------------------

COMBOBOX_HTML = """
<html><body>
  <button aria-haspopup="listbox" aria-expanded="false" aria-controls="opts">Choose</button>
  <ul id="opts" role="listbox" style="display:none">
    <li role="option">Alpha</li>
    <li role="option">Beta</li>
  </ul>
</body></html>
"""


@pytest.mark.asyncio
async def test_combobox_trigger_reports_expanded_state_and_options():
    async with Browser(headless=True) as browser:
        page = await open_with_html(browser, COMBOBOX_HTML)
        try:
            rows = await _discover(page)
            trigger = next(r for r in rows if r["text"] == "Choose")
            assert trigger["isCombobox"] is True
            assert trigger["comboboxExpanded"] is False
            assert trigger["comboboxOptions"] == ["Alpha", "Beta"]
        finally:
            await page.close()


@pytest.mark.asyncio
async def test_ordinary_button_is_not_flagged_as_a_combobox():
    async with Browser(headless=True) as browser:
        page = await open_with_html(
            browser, "<html><body><button>Submit</button></body></html>"
        )
        try:
            rows = await _discover(page)
            button = next(r for r in rows if r["text"] == "Submit")
            assert button["isCombobox"] is False
            assert button["comboboxExpanded"] is None
            assert button["comboboxOptions"] is None
        finally:
            await page.close()
