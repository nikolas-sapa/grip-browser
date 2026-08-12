"""Real-Chrome proof for the non-semantic-clickable probe pass.

`benchmarks/corpus/fixtures/spa_01.html` is the exact fixture a 30-task
LLM-in-the-loop benchmark scored grip 0/10 on: its catalog items are
`<div class="item" data-id="N">` with only a JS `addEventListener('click')` —
no role, no tabindex, no cursor:pointer. Before the probe pass, DISCOVER never
produced a handle for them, so `click("Item 1-4")` correctly (but uselessly)
raised ELEMENT_NOT_FOUND. This test proves the fix: the div now appears in the
snapshot and `click()` by description actually flips the fixture's own state.

The fixture is read-only and untouched here.
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from grip.browser import Browser

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "benchmarks" / "corpus" / "fixtures" / "spa_01.html"
)


def _serve(body: bytes):
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
    # (SSRF guard), so the Browser below opts in with allow_private=True.
    httpd = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_port}", httpd


@pytest.fixture
def spa_01_url():
    body = FIXTURE_PATH.read_bytes()
    url, httpd = _serve(body)
    yield url
    httpd.shutdown()


@pytest.mark.asyncio
async def test_click_by_description_selects_the_non_semantic_catalog_item(spa_01_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(spa_01_url)
        await page.snapshot()

        # Item 1-4 (id=4, category "Toys") sits on page 2 of the unfiltered
        # default sort; filtering to "Toys" brings it to page 1 as the only
        # match, mirroring how the benchmark task reaches it.
        await page.select("Category", "Toys")
        snap = await page.snapshot()

        # The div itself IS the click target (`d.addEventListener('click', ...)`
        # on the created <div>, not a delegated ancestor listener), so it must
        # show up as its own snapshot element with its own accessible text.
        item_texts = [e.text for e in snap.elements if "Item 1-4" in e.text]
        assert item_texts, (
            "div.item[data-id=4] never reached the snapshot - the probe pass "
            "regressed back to semantic-only discovery"
        )

        # This is the exact call that failed 10/10 on the benchmark.
        await page.click("Item 1-4")

        state = await page._eval("(function(){ return window.__bench_state(); })()")
        assert state["selected"] == 4, (
            f"click() did not reach div.item[data-id=4]'s listener; state={state}"
        )


@pytest.mark.asyncio
async def test_probe_pass_has_two_false_positive_controls_in_this_fixture(spa_01_url):
    """Two natural false-positive controls already present in this fixture:

    - `<div id="list">` only ever holds element children (the JS clears and
      rebuilds it via appendChild), so it never has a direct text node of its
      own and must be excluded before any listener probe runs at all.
    - `<span id="pageno">Page 1 of 3</span>` has its own text and reaches the
      JS shortlist, but never registers a click listener, so the CDP
      DOMDebugger.getEventListeners check must filter it back out.
    """
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(spa_01_url)
        snap = await page.snapshot()

    for el in snap.elements:
        assert el.handle != "", "every collected element must carry a stamped handle"
    texts = [e.text for e in snap.elements]
    assert not any(t.strip() == "" for t in texts), (
        "an empty-text element reached the snapshot; the container-div control failed"
    )
    pageno_entries = [e for e in snap.elements if e.text.strip().startswith("Page ")]
    assert pageno_entries == [], (
        "#pageno has no click listener and must not be offered as clickable: "
        f"{pageno_entries}"
    )
