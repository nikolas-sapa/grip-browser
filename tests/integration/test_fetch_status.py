"""
A blocked fetch must not report success. Ticket 06.
Uses a local server so the test does not depend on a live site's anti-bot mood.
"""
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from grip.browser import Browser
from grip.errors.types import ErrorType


class _Handler(BaseHTTPRequestHandler):
    """/<status> returns that status. Body mimics a Cloudflare interstitial."""

    def do_GET(self):
        try:
            status = int(self.path.strip("/") or 200)
        except ValueError:
            status = 200
        body = b"<html><head><title>Just a moment...</title></head><body>x</body></html>"
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _OkHandler(_Handler):
    def do_GET(self):
        body = b"<html><head><title>Example Domain</title></head><body>hello</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    def _start(handler):
        httpd = HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd

    servers = []

    def factory(handler):
        httpd = _start(handler)
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_port}"

    yield factory
    for httpd in servers:
        httpd.shutdown()


@pytest.mark.asyncio
async def test_403_surfaces_as_anti_bot_block(server):
    base = server(_Handler)
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(f"{base}/403")
        snap = await page.snapshot()
        assert page._status_code == 403
        assert snap.page_error is not None, "a 403 fetch reported success"
        assert snap.page_error.type == ErrorType.ANTI_BOT_BLOCK


@pytest.mark.asyncio
async def test_429_surfaces_as_rate_limited(server):
    base = server(_Handler)
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(f"{base}/429")
        snap = await page.snapshot()
        assert snap.page_error is not None
        assert snap.page_error.type == ErrorType.RATE_LIMITED


@pytest.mark.asyncio
async def test_just_a_moment_title_blocks_even_on_200(server):
    """Cloudflare sometimes serves the interstitial with a 200."""
    base = server(_Handler)
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(f"{base}/200")
        snap = await page.snapshot()
        assert snap.page_error is not None
        assert snap.page_error.type == ErrorType.ANTI_BOT_BLOCK


@pytest.mark.asyncio
async def test_thin_legitimate_page_stays_clean(server):
    """Guards the false positive: a small real page must not be flagged."""
    base = server(_OkHandler)
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base)
        snap = await page.snapshot()
        assert page._status_code == 200
        assert snap.page_error is None


class _SoftNotFoundHandler(_Handler):
    """A client-router-style soft 404: real 200, ordinary body, title says it."""

    def do_GET(self):
        body = (
            b"<html><head><title>Page not found | MySite</title></head>"
            b"<body><p>We couldn't find what you were looking for.</p></body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.mark.asyncio
async def test_soft_404_title_surfaces_as_no_content(server):
    base = server(_SoftNotFoundHandler)
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base)
        snap = await page.snapshot()
        assert page._status_code == 200
        assert snap.page_error is not None
        assert snap.page_error.type == ErrorType.NO_CONTENT


@pytest.mark.asyncio
async def test_status_is_captured_per_tab_under_concurrency(server):
    """Each tab owns its own status — no leaking between concurrent fetches."""
    base = server(_Handler)
    ok = server(_OkHandler)
    async with Browser(headless=True, allow_private=True) as browser:
        blocked, fine = await asyncio.gather(
            browser.open(f"{base}/403"), browser.open(ok)
        )
        assert blocked._status_code == 403
        assert fine._status_code == 200
