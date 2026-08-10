"""
Read mode: a page as prose, not as controls. Ticket 03.
Local server so the content is deterministic.
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from grip.browser import Browser

PAGE = b"""<html><head><title>Widget Docs</title></head><body>
  <nav><a href="/a">Home</a><a href="/b">Pricing</a><a href="/c">Careers</a></nav>
  <div class="cookie-banner"><p>We use cookies to improve your experience.</p></div>
  <main>
    <h1>Widgets</h1>
    <p>A widget is a small thing.</p>
    <h2>Installation</h2>
    <p>Run the installer.</p>
    <pre>pip install widget</pre>
    <h3>Troubleshooting</h3>
    <p>Turn it off and on again.</p>
    <h2>Licence</h2>
    <p>MIT.</p>
  </main>
  <footer><p>Copyright 2026 Widget Corp. All rights reserved.</p></footer>
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
async def test_read_drops_navigation_and_footer_chrome(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        doc = await page.read()
        text = doc.text
        assert "A widget is a small thing." in text
        assert "Pricing" not in text
        assert "Careers" not in text
        assert "All rights reserved" not in text
        assert "We use cookies" not in text


@pytest.mark.asyncio
async def test_blocks_carry_a_heading_breadcrumb(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        doc = await page.read()
        troubleshooting = next(
            b for b in doc.blocks if "Turn it off" in b.text
        )
        assert troubleshooting.path == ["Widgets", "Installation", "Troubleshooting"]


@pytest.mark.asyncio
async def test_heading_trail_pops_back_out_on_a_shallower_heading(base_url):
    """After an h3, an h2 must reset the trail rather than nest under it."""
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        doc = await page.read()
        licence = next(b for b in doc.blocks if b.text == "MIT.")
        assert licence.path == ["Widgets", "Licence"]


@pytest.mark.asyncio
async def test_code_blocks_are_marked(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        doc = await page.read()
        code = [b for b in doc.blocks if b.kind == "code"]
        assert len(code) == 1
        assert code[0].text == "pip install widget"


@pytest.mark.asyncio
async def test_outline_reflects_heading_depth(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        doc = await page.read()
        outline = doc.outline()
        assert "Widgets" in outline
        assert "  Installation" in outline
        assert "    Troubleshooting" in outline


@pytest.mark.asyncio
async def test_max_chars_drops_whole_blocks(base_url):
    """Truncation must never cut a block mid-sentence."""
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        full = await page.read()
        clipped = await page.read(max_chars=30)
        assert len(clipped) < len(full)
        for block in clipped.blocks:
            assert any(b.text == block.text for b in full.blocks)


@pytest.mark.asyncio
async def test_citation_is_stable_and_readable(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        doc = await page.read()
        block = next(b for b in doc.blocks if "Turn it off" in b.text)
        assert block.citation == f"[{block.id}] Widgets › Installation › Troubleshooting"


@pytest.mark.asyncio
async def test_read_and_snapshot_answer_different_questions(base_url):
    """snapshot() sees controls including nav links; read() sees prose."""
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        snap = await page.snapshot()
        doc = await page.read()
        assert any("Pricing" in t for t, _ in snap.links)
        assert "Pricing" not in doc.text
