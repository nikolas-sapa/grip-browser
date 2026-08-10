"""
`page.click(i)` and `page.type(i)` are handed an index produced by
`snapshot()`. If those three build their candidate lists by different rules, the
index silently points at a different element and the agent acts on the wrong
thing.

They used to. DISCOVER treated an element as hidden on six conditions, CLICK on
two, and TYPE collected an entirely different input-only set. These tests pin the
three lists together on pages built to expose exactly that drift.
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from grip.browser import Browser

# Every element here is invisible to DISCOVER but was visible to the old CLICK
# rules, so each one shifted CLICK's indices by one relative to the snapshot.
DRIFT_PAGE = b"""<html><body>
  <button aria-hidden="true">Aria hidden button</button>
  <button style="opacity: 0">Transparent button</button>
  <button style="width:0;height:0;padding:0;border:0">Zero size button</button>
  <a href="https://example.com/one" aria-hidden="true">Hidden link</a>

  <button id="real1">First Real Button</button>
  <a href="https://example.com/two">Real Link</a>
  <button id="real2">Second Real Button</button>

  <span id="clicked">nothing</span>
  <script>
    document.getElementById('real1').onclick = function () {
      document.getElementById('clicked').textContent = 'first';
    };
    document.getElementById('real2').onclick = function () {
      document.getElementById('clicked').textContent = 'second';
    };
  </script>
</body></html>"""

# Buttons and a link precede the input. TYPE used to collect only inputs, so the
# input sat at index 0 in its list while the snapshot placed it much later.
INPUT_AFTER_CONTROLS = b"""<html><body>
  <button>Alpha</button>
  <button>Beta</button>
  <a href="https://example.com/x">Gamma</a>
  <input id="target" type="text" placeholder="search here" />
  <textarea id="notes" placeholder="notes here"></textarea>
</body></html>"""


def _serve(body):
    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    # Loopback fixture: NavigationPolicy refuses private addresses by default
    # (SSRF guard), so every Browser here opts in with allow_private=True.
    httpd = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_port}", httpd


@pytest.fixture
def drift_url():
    url, httpd = _serve(DRIFT_PAGE)
    yield url
    httpd.shutdown()


@pytest.fixture
def input_url():
    url, httpd = _serve(INPUT_AFTER_CONTROLS)
    yield url
    httpd.shutdown()


@pytest.mark.asyncio
async def test_snapshot_omits_hidden_controls(drift_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(drift_url)
        snap = await page.snapshot()
    texts = [e.text for e in snap.elements]
    for hidden in ("Aria hidden", "Transparent", "Zero size", "Hidden link"):
        assert not any(hidden in t for t in texts), f"{hidden!r} leaked into {texts}"


@pytest.mark.asyncio
async def test_click_lands_on_the_element_the_snapshot_named(drift_url):
    """The regression: four hidden controls precede the real ones, so any rule
    mismatch makes click() land several elements away from the one matched."""
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(drift_url)
        await page.snapshot()
        await page.click("Second Real Button")
        result = await page._engine.send(
            "Runtime.evaluate",
            {"expression": "document.getElementById('clicked').textContent",
             "returnByValue": True},
        )
    assert result["result"]["value"] == "second"


@pytest.mark.asyncio
async def test_click_lands_on_the_first_button_too(drift_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(drift_url)
        await page.snapshot()
        await page.click("First Real Button")
        result = await page._engine.send(
            "Runtime.evaluate",
            {"expression": "document.getElementById('clicked').textContent",
             "returnByValue": True},
        )
    assert result["result"]["value"] == "first"


@pytest.mark.asyncio
async def test_type_reaches_the_input_behind_other_controls(input_url):
    """TYPE built an input-only list, so an input preceded by buttons sat at a
    different index than the snapshot reported. Passing tests elsewhere only hid
    this because their fixtures put the input first."""
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(input_url)
        await page.snapshot()
        await page.type("search here", "blue sneakers")
        result = await page._engine.send(
            "Runtime.evaluate",
            {"expression": "document.getElementById('target').value",
             "returnByValue": True},
        )
    assert result["result"]["value"] == "blue sneakers"


@pytest.mark.asyncio
async def test_type_reaches_the_second_input(input_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(input_url)
        await page.snapshot()
        await page.type("notes here", "some notes")
        result = await page._engine.send(
            "Runtime.evaluate",
            {"expression": "document.getElementById('notes').value",
             "returnByValue": True},
        )
    assert result["result"]["value"] == "some notes"
