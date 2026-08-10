"""
Real Chrome integration test — launches actual Chrome, browses a local
example.com-shaped fixture (no network dependency; see base_url below).
Run: .venv/bin/python3 -m pytest tests/integration/ -v -s
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from grip.browser import Browser
from grip.compression.summarizer import PageSnapshot

# Mirrors https://example.com closely enough for the assertions below
# (title, some prose) without a network dependency in CI.
_PAGE = b"""<html><head><title>Example Domain</title></head><body>
  <div>
    <h1>Example Domain</h1>
    <p>This domain is for use in illustrative examples in documents. You may
    use this domain in literature without prior coordination or asking for
    permission.</p>
    <p><a href="https://www.iana.org/domains/example">More information...</a></p>
  </div>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(_PAGE)))
        self.end_headers()
        self.wfile.write(_PAGE)

    def log_message(self, *args):
        pass


@pytest.fixture
def base_url():
    # Loopback fixture: NavigationPolicy refuses private addresses by default
    # (SSRF guard), so every Browser here opts in with allow_private=True.
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/"
    httpd.shutdown()


@pytest.mark.asyncio
async def test_snapshot_real_page(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        snapshot = await page.snapshot()

        assert isinstance(snapshot, PageSnapshot)
        assert "example" in snapshot.title.lower()
        assert snapshot.tokens_estimated > 0
        assert snapshot.version == 1
        print(f"\nURL: {snapshot.url}")
        print(f"Title: {snapshot.title}")
        print(f"Elements: {len(snapshot.elements)}")
        print(f"Tokens: {snapshot.tokens_estimated}")
        print(f"Text snippet: {snapshot.text_content[:200]}")


@pytest.mark.asyncio
async def test_format_output_looks_right(base_url):
    from grip.compression.summarizer import Summarizer
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        snapshot = await page.snapshot()
        summarizer = Summarizer()
        formatted = summarizer.format(snapshot)
        print(f"\n--- Formatted output ---\n{formatted}\n---")
        assert "PAGE:" in formatted
        assert "URL:" in formatted
        assert len(formatted) < 5000


@pytest.mark.asyncio
async def test_read_returns_prose(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        doc = await page.read()
        print(f"\nRead result:\n{doc.text}")
        assert len(doc.text) > 10


@pytest.mark.asyncio
async def test_screenshot(base_url):
    from grip.page import Screenshot
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        shot = await page.screenshot(quality=75)

        assert isinstance(shot, Screenshot)
        assert len(shot.data) > 1000          # real image, not empty
        assert shot.data[:2] == b"\xff\xd8"   # JPEG magic bytes
        assert len(shot.b64) > 0
        assert shot.tokens_estimated > 0

        print(f"\nScreenshot: {len(shot.data):,} bytes, ~{shot.tokens_estimated} tokens")
        print(f"DOM snapshot was ~50 tokens — screenshot is {shot.tokens_estimated / 50:.0f}x more")
        shot.save("/tmp/grip_test.jpg")
        print("Saved to /tmp/grip_test.jpg")
