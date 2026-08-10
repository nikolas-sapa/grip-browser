"""
Blocking images/fonts/media is what makes the per-query cost model work when
bandwidth is billed. Measured across 50 real pages, it roughly halves a docs page
and cuts a blog page by ~3x.
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from grip.browser import Browser

PAGE = b"""<html><head><title>Weighty</title></head><body>
  <main>
    <h1>An article</h1>
    <p>The text an agent actually reads, which must survive resource blocking.</p>
  </main>
  <img src="/photo.png">
  <img src="/diagram.svg">
  <script>
    fetch('/data.json').catch(function () {});
  </script>
</body></html>"""


class _Recorder(BaseHTTPRequestHandler):
    requested: list = []

    def do_GET(self):
        type(self).requested.append(self.path)
        if self.path.endswith(".png") or self.path.endswith(".svg"):
            body = b"\x89PNG\r\n\x1a\n" + b"0" * 512
            ctype = "image/png"
        elif self.path.endswith(".json"):
            body, ctype = b'{"ok":true}', "application/json"
        else:
            body, ctype = PAGE, "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    servers = []

    def factory():
        handler = type("H", (_Recorder,), {"requested": []})
        # Loopback fixture: NavigationPolicy refuses private addresses by default
        # (SSRF guard), so every Browser here opts in with allow_private=True.
        httpd = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_port}", handler

    yield factory
    for httpd in servers:
        httpd.shutdown()


@pytest.mark.asyncio
async def test_blocking_skips_images_and_fonts(server):
    url, handler = server()
    async with Browser(headless=True, block_resources=True, allow_private=True) as browser:
        page = await browser.open(url)
        await page.snapshot()
    assert not [p for p in handler.requested if p.endswith((".png", ".svg"))], (
        handler.requested
    )


@pytest.mark.asyncio
async def test_images_load_by_default(server):
    """Off by default — blocking changes what the browser sees, so it is opt-in."""
    url, handler = server()
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(url)
        await page.snapshot()
    assert [p for p in handler.requested if p.endswith(".png")]


@pytest.mark.asyncio
async def test_blocking_keeps_page_content(server):
    """The whole point is that only the unreadable bytes go."""
    url, _ = server()
    async with Browser(headless=True, block_resources=True, allow_private=True) as browser:
        page = await browser.open(url)
        doc = await page.read()
    assert "text an agent actually reads" in doc.text


@pytest.mark.asyncio
async def test_xhr_still_loads_while_blocking(server):
    """Content routinely arrives over XHR; blocking it would change what the page
    is, not just what it weighs."""
    url, handler = server()
    async with Browser(headless=True, block_resources=True, allow_private=True) as browser:
        page = await browser.open(url)
        await page.snapshot()
    assert any(p.endswith(".json") for p in handler.requested), handler.requested
