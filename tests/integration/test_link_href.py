"""
Links must report where they go. Ticket 07.
Local server so hrefs are deterministic.
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from grip.browser import Browser

PAGE = b"""<html><body>
  <a href="/relative/path">Relative</a>
  <a href="https://example.com/absolute">Absolute</a>
  <a href="mailto:someone@example.com">Mail</a>
  <a href="javascript:void(0)">JS</a>
  <a href="#section">Fragment</a>
  <a href="tel:+15551234">Phone</a>
  <a>No href at all</a>
  <button>Not a link</button>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args):
        pass


@pytest.fixture
def base_url():
    # Loopback fixture: NavigationPolicy refuses private addresses by default
    # (SSRF guard), so every Browser here opts in with allow_private=True.
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


@pytest.mark.asyncio
async def test_relative_href_is_resolved_to_absolute(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        snap = await page.snapshot()
        hrefs = dict(snap.links)
        assert hrefs["Relative"] == f"{base_url}/relative/path"


@pytest.mark.asyncio
async def test_absolute_href_is_preserved(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        snap = await page.snapshot()
        assert dict(snap.links)["Absolute"] == "https://example.com/absolute"


@pytest.mark.asyncio
async def test_unfetchable_schemes_are_dropped(base_url):
    """mailto/javascript/tel/#fragment are not pages — a fetcher cannot use them."""
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        snap = await page.snapshot()
        texts = {t for t, _ in snap.links}
        assert texts == {"Relative", "Absolute"}
        for bad in ("Mail", "JS", "Fragment", "Phone", "No href at all"):
            assert bad not in texts


@pytest.mark.asyncio
async def test_non_link_elements_have_no_href(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        snap = await page.snapshot()
        buttons = [e for e in snap.elements if e.tag == "button"]
        assert buttons and all(e.href is None for e in buttons)


@pytest.mark.asyncio
async def test_hrefs_stay_out_of_the_formatted_snapshot(base_url):
    """The formatted string is the token-budget surface; URLs would swamp a SERP."""
    from grip.compression.summarizer import Summarizer

    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        snap = await page.snapshot()
        formatted = Summarizer().format(snap)
        assert "https://example.com/absolute" not in formatted
        assert snap.links  # but they are available structurally
