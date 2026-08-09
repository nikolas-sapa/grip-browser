"""
Content-shape detection: pages that return 200 with an ordinary title but
whose real content, after chrome (nav/cookie/consent/promo) stripping, is
almost nothing — the pattern the silent-failure evaluation found on consent
walls (evaluation/SILENT_FAILURE.md). Ticket: extend classify_page_state
beyond title/status patterns.

False positives are strictly worse than misses here (a flagged source is
dropped unread), so this file leans on control pages as much as the
positive case: a real long article, and a real page whose content the
extractor structurally can't isolate (prose in bare <div>s, no <p>/<li>).
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from grip.browser import Browser
from grip.errors.types import ErrorType


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        body = self.body()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

    def body(self) -> bytes:  # overridden per handler
        raise NotImplementedError


_COOKIE_FILLER = (
    "We use cookies and similar technologies to enhance your browsing "
    "experience, serve personalised ads or content, and analyse our "
    "traffic. By clicking Accept All, you consent to our use of cookies. "
    "You can manage your preferences at any time in Cookie Settings. "
) * 2


class _ConsentWallHandler(_Handler):
    """Ordinary title, 200, real-looking page — but the only real content is
    two words; everything else is cookie-banner chrome (matches READ_CONTENT_JS's
    'cookie'/'consent' class-name filter, same mechanism as the nav/footer tags)."""

    def body(self) -> bytes:
        html = (
            "<html><head><title>Top Content on MySite</title></head><body>"
            f'<nav class="cookie-consent-banner"><p>{_COOKIE_FILLER}</p></nav>'
            "<p>Editor's Picks</p>"
            "</body></html>"
        )
        return html.encode()


_ARTICLE_PARAGRAPHS = [
    "The history of the region stretches back several centuries, shaped by "
    "trade routes that connected distant markets and cultures. Early "
    "settlements grew around river crossings, where merchants exchanged "
    "goods and ideas that would eventually reshape the wider economy.",
    "Over time, these settlements matured into towns with their own "
    "governance, markets, and craft guilds. Historians point to this period "
    "as the foundation for much of the region's later architectural and "
    "civic character, visible today in its surviving town squares.",
    "Modern scholarship continues to revisit these records, using newly "
    "digitised archives to trace population movements and trade volumes "
    "with a precision earlier historians could only estimate from partial "
    "ledgers and travellers' accounts.",
]


class _LongArticleHandler(_Handler):
    """A real, mostly-prose page: content should roughly match raw length."""

    def body(self) -> bytes:
        paras = "".join(f"<p>{p}</p>" for p in _ARTICLE_PARAGRAPHS)
        html = f"<html><head><title>A Long Real Article</title></head><body>{paras}</body></html>"
        return html.encode()


class _DivOnlyHandler(_Handler):
    """Real content, but sitting in a bare <div> with no <p>/<li>/etc — the
    extractor structurally can't isolate it. Must NOT be flagged: content_chars
    lands at 0, which the classifier treats as its own limitation, not a block."""

    def body(self) -> bytes:
        html = (
            "<html><head><title>My App</title></head><body>"
            f"<div>{_ARTICLE_PARAGRAPHS[0]} {_ARTICLE_PARAGRAPHS[1]}</div>"
            "</body></html>"
        )
        return html.encode()


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
async def test_consent_wall_shape_surfaces_as_no_content(server):
    base = server(_ConsentWallHandler)
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base)
        snap = await page.snapshot()
        assert page._status_code == 200
        assert snap.page_error is not None, "cookie-wall shape reported success"
        assert snap.page_error.type == ErrorType.NO_CONTENT


@pytest.mark.asyncio
async def test_long_real_article_stays_clean(server):
    """Content roughly matches raw length — must not be flagged even though
    both numbers are well above the probe floor."""
    base = server(_LongArticleHandler)
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base)
        snap = await page.snapshot()
        assert page._status_code == 200
        assert snap.page_error is None


@pytest.mark.asyncio
async def test_prose_in_bare_divs_stays_clean(server):
    """The extractor finds zero blocks (no <p>/<li> to anchor on) — treated
    as its own limitation, not evidence of a block."""
    base = server(_DivOnlyHandler)
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base)
        snap = await page.snapshot()
        assert page._status_code == 200
        assert snap.page_error is None


@pytest.mark.asyncio
async def test_content_shape_is_probed_once_per_url(server):
    """snapshot() is the hot path and the probe is a second JS evaluation. The
    verdict describes the fetch, so it cannot change between snapshots of the same
    URL — re-running it would cost latency for no new information."""
    base = server(_ConsentWallHandler)
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base)
        calls = 0
        original = page._probe_content_shape

        async def counting():
            nonlocal calls
            calls += 1
            return await original()

        page._probe_content_shape = counting
        first = await page.snapshot()
        await page.snapshot()
        await page.snapshot()

        assert calls == 1, f"probed {calls} times for one URL"
        assert first.page_error is not None
