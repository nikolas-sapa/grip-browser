"""
Interaction-to-reveal: content that only exists after a click/scroll. Ticket 09.
Local server so the content is deterministic, same pattern as test_read_mode.py.
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from grip.browser import Browser

# "Show more" reveals one paragraph on first click, then no-ops — exercises
# recovery and the plateau stop (second click adds 0 new blocks).
SHOW_MORE_PAGE = b"""<html><head><title>Article</title></head><body>
  <main>
    <h1>Article</h1>
    <p>Intro paragraph.</p>
    <div id="extra"></div>
    <button id="more">Show more</button>
  </main>
  <script>
    document.getElementById('more').addEventListener('click', function () {
      if (document.getElementById('extra').children.length > 0) return;
      var p = document.createElement('p');
      p.textContent = 'Revealed content after interaction.';
      document.getElementById('extra').appendChild(p);
    });
  </script>
</body></html>"""

# "Load more" appends a new, always-distinct paragraph every click, forever —
# exercises the depth cap since it would never plateau on its own.
LOAD_MORE_PAGE = b"""<html><head><title>Feed</title></head><body>
  <main>
    <h1>Feed</h1>
    <p>Intro paragraph.</p>
    <div id="feed"></div>
    <button id="more">Load more</button>
  </main>
  <script>
    var n = 0;
    document.getElementById('more').addEventListener('click', function () {
      n++;
      var p = document.createElement('p');
      p.textContent = 'chunk-' + n;
      document.getElementById('feed').appendChild(p);
    });
  </script>
</body></html>"""

# "Expand" matches the reveal heuristic but changes nothing in the DOM —
# exercises the plateau stop directly, with a click counter to prove the loop
# only fired once even though max_interactions allows more.
DEAD_BUTTON_PAGE = b"""<html><head><title>Static</title></head><body>
  <main>
    <h1>Static</h1>
    <p>Intro paragraph.</p>
  </main>
  <button id="expand" onclick="window.__clicks = (window.__clicks || 0) + 1">Expand</button>
</body></html>"""

# "Next" is a real paginated-site link, not a same-page expander — clicking it
# navigates. Exercises the guard that keeps interaction on the current document.
PAGINATED_PAGE = b"""<html><head><title>Page One</title></head><body>
  <main>
    <h1>Page One</h1>
    <p>Page one body.</p>
  </main>
  <a href="/show-more">Next</a>
</body></html>"""

# Appends its paragraph inside a setTimeout, like a real fetch-backed "load
# more" — exercises the poll (a fixed short sleep would miss this).
ASYNC_LOAD_PAGE = b"""<html><head><title>Async Feed</title></head><body>
  <main>
    <h1>Async Feed</h1>
    <p>Intro paragraph.</p>
    <div id="feed"></div>
    <button id="more">Load more</button>
  </main>
  <script>
    document.getElementById('more').addEventListener('click', function () {
      setTimeout(function () {
        var p = document.createElement('p');
        p.textContent = 'Async chunk arrived.';
        document.getElementById('feed').appendChild(p);
      }, 300);
    });
  </script>
</body></html>"""

# A div-based expander with no matching text, only aria-expanded=false —
# exercises the second (aria) branch of the reveal heuristic.
ARIA_EXPANDER_PAGE = b"""<html><head><title>Details</title></head><body>
  <main>
    <h1>Details</h1>
    <p>Intro paragraph.</p>
    <div id="panel"></div>
    <div id="toggle" role="button" aria-expanded="false">Details</div>
  </main>
  <script>
    document.getElementById('toggle').addEventListener('click', function () {
      this.setAttribute('aria-expanded', 'true');
      var p = document.createElement('p');
      p.textContent = 'Panel content.';
      document.getElementById('panel').appendChild(p);
    });
  </script>
</body></html>"""

_ROUTES = {
    "/show-more": SHOW_MORE_PAGE,
    "/load-more": LOAD_MORE_PAGE,
    "/dead-button": DEAD_BUTTON_PAGE,
    "/paginated": PAGINATED_PAGE,
    "/async-load": ASYNC_LOAD_PAGE,
    "/aria-expander": ARIA_EXPANDER_PAGE,
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        page = _ROUTES.get(self.path, SHOW_MORE_PAGE)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

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
async def test_hidden_content_absent_without_interact_flag(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(f"{base_url}/show-more")
        doc = await page.read()
        assert "Revealed content after interaction." not in doc.text


@pytest.mark.asyncio
async def test_hidden_content_recovered_with_interact_flag(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(f"{base_url}/show-more")
        doc = await page.read(interact=True)
        assert "Revealed content after interaction." in doc.text


@pytest.mark.asyncio
async def test_depth_cap_limits_interactions(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(f"{base_url}/load-more")
        doc = await page.read(interact=True, max_interactions=1)
        assert "chunk-1" in doc.text
        assert "chunk-2" not in doc.text  # would exist by interaction 2, cap stops it


@pytest.mark.asyncio
async def test_plateau_stops_the_loop_early(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(f"{base_url}/dead-button")
        await page.read(interact=True, max_interactions=3)
        result = await page._engine.send(
            "Runtime.evaluate",
            {"expression": "window.__clicks || 0", "returnByValue": True},
        )
        clicks = result.get("result", {}).get("value", 0)
        # A dead button adds zero new blocks, so the plateau check must stop
        # after the first interaction rather than spending the full depth cap.
        assert clicks == 1


@pytest.mark.asyncio
async def test_block_ids_contiguous_and_assigned_once(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(f"{base_url}/show-more")
        doc = await page.read(interact=True)
        ids = [b.id for b in doc.blocks]
        assert ids == list(range(len(doc.blocks)))
        revealed = next(b for b in doc.blocks if "Revealed content" in b.text)
        assert revealed.id == len(doc.blocks) - 1  # last block in final DOM order


@pytest.mark.asyncio
async def test_default_read_behaviour_is_unchanged(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(f"{base_url}/show-more")
        doc = await page.read()
        assert [b.text for b in doc.blocks] == ["Article", "Intro paragraph."]


@pytest.mark.asyncio
async def test_default_max_interactions_is_three(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(f"{base_url}/load-more")
        doc = await page.read(interact=True)  # max_interactions defaults to 3
        assert "chunk-3" in doc.text
        assert "chunk-4" not in doc.text


@pytest.mark.asyncio
async def test_a_next_link_does_not_navigate_away(base_url):
    """A paginated 'Next' link must not be followed — clicking it would hand
    back a different document mid-loop, breaking citation stability."""
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(f"{base_url}/paginated")
        doc = await page.read(interact=True)
        assert doc.url.rstrip("/").endswith("/paginated")
        assert "Page one body." in doc.text


@pytest.mark.asyncio
async def test_async_load_more_is_recovered(base_url):
    """Content appended after a delayed fetch-like callback, not synchronously
    on click, must still be picked up (the poll, not a fixed sleep)."""
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(f"{base_url}/async-load")
        doc = await page.read(interact=True)
        assert "Async chunk arrived." in doc.text


@pytest.mark.asyncio
async def test_aria_expanded_false_is_treated_as_a_reveal_control(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(f"{base_url}/aria-expander")
        without = await page.read()
        assert "Panel content." not in without.text

        with_interact = await page.read(interact=True)
        assert "Panel content." in with_interact.text
