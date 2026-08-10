"""select() against real Chrome. Same pattern as test_interaction_reveal.py.

The assertion that matters here is not that <select>.value changed — a raw
value assignment does that too, and a framework-bound component would never
notice. It is that a 'change' event actually reached a JS listener, the way
it would from a real user picking an option, so a React/Vue-style controlled
<select> re-renders in response.
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from grip.browser import Browser
from grip.errors import GripError
from grip.errors.types import ErrorType

_FORM_01 = (
    Path(__file__).resolve().parents[2]
    / "benchmarks" / "corpus" / "fixtures" / "form_01.html"
)

# Simulates a controlled <select> the way React (and most SPA frameworks)
# actually wires one up: a single listener attached higher up the tree,
# relying on the change event bubbling to it — React <18 delegates at
# `document`, 18+ at the root container, but both need `bubbles: true` to
# ever see the event at all. State only updates from that listener, never
# from watching the element directly, so this fails exactly the way a real
# framework component would if select() only assigned `.value`.
SELECT_PAGE = b"""<html><head><title>Signup</title></head><body>
  <main>
    <h1>Signup</h1>
    <label for="role">Role</label>
    <select id="role">
      <option value="">Choose...</option>
      <option value="eng">Engineer</option>
      <option value="eng-sr">Engineer (Senior)</option>
      <option value="mgr">Manager</option>
    </select>
    <div id="output">none</div>
  </main>
  <script>
    document.addEventListener('change', function (e) {
      if (e.target && e.target.id === 'role') {
        document.getElementById('output').textContent = 'selected:' + e.target.value;
      }
    });
  </script>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(SELECT_PAGE)))
        self.end_headers()
        self.wfile.write(SELECT_PAGE)

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


async def _output_text(page):
    result = await page._engine.send(
        "Runtime.evaluate",
        {"expression": "document.getElementById('output').textContent", "returnByValue": True},
    )
    return result.get("result", {}).get("value", "")


async def _select_ref(page):
    """The snapshot ref for the page's one <select>. Kept as a ref-based path
    alongside the description-based tests below (test_select_resolves_by_
    accessible_label) so both entry points into select() stay covered."""
    snap = await page.snapshot()
    select_el = next(el for el in snap.elements if el.tag == "select")
    return select_el.ref


@pytest.mark.asyncio
async def test_select_by_visible_text_fires_change_event(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        ref = await _select_ref(page)
        await page.select(ref, "Manager")
        # Proves the change event actually reached a listener bound higher up
        # the tree, not just that the element's own .value changed.
        assert await _output_text(page) == "selected:mgr"


@pytest.mark.asyncio
async def test_select_by_value_attribute_when_text_does_not_match(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        ref = await _select_ref(page)
        # "eng" is Engineer's `value`, not its visible text ("Engineer") — this
        # only resolves through the value-attribute fallback.
        await page.select(ref, "eng")
        assert await _output_text(page) == "selected:eng"


@pytest.mark.asyncio
async def test_select_exact_text_matches_before_substring(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        ref = await _select_ref(page)
        # "Engineer" is itself an exact option text and also a substring of
        # "Engineer (Senior)" — exact match must win, not raise on ambiguity.
        await page.select(ref, "Engineer")
        assert await _output_text(page) == "selected:eng"


@pytest.mark.asyncio
async def test_select_raises_typed_error_for_missing_option(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        ref = await _select_ref(page)
        with pytest.raises(GripError) as exc:
            await page.select(ref, "Intern")
        assert exc.value.error.type is ErrorType.ELEMENT_NOT_FOUND
        assert "Engineer" in exc.value.error.message


@pytest.mark.asyncio
async def test_select_resolves_by_accessible_label(base_url):
    """The decisive case grip/cdp/shadow.py's label-resolution change exists
    for: a <select> whose own text is just its option dump ("Choose...
    Engineer...") must still resolve through a fuzzy description matching its
    sibling <label for=...>, exactly like a sighted user reading "Role" next
    to the dropdown. Before the fix this failed — DISCOVER never read the
    label, so _find_select's substring match against el.text had nothing of
    "Role" to match."""
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        await page.snapshot()
        await page.select("Role", "Manager")
        assert await _output_text(page) == "selected:mgr"


@pytest.mark.asyncio
async def test_select_raises_when_description_matches_no_select(base_url):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        await page.snapshot()
        # "Signup" only matches the <h1> — _find_select is tag-filtered to
        # <select>, so this is a semantic miss, not a not-a-select outcome.
        with pytest.raises(GripError) as exc:
            await page.select("Signup", "Manager")
        assert exc.value.error.type is ErrorType.ELEMENT_NOT_FOUND


class _Form01Handler(BaseHTTPRequestHandler):
    """Serves the real corpus fixture unmodified (read-only per the audit
    constraints) so the pipeline is exercised against the exact bytes the
    benchmark uses, not a hand-copied stand-in that could drift from it."""

    def do_GET(self):
        body = _FORM_01.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def form_01_url():
    httpd = HTTPServer(("127.0.0.1", 0), _Form01Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


@pytest.mark.asyncio
async def test_form_01_select_role_by_description(form_01_url):
    """benchmarks/corpus/fixtures/form_01.html's <select id="role"> has no own
    identifying text beyond its option dump — only its sibling <label for=
    "role">Role</label> names it for a sighted user. This is the exact case
    the team lead flagged as failing before the fix and the reason the work
    was done; page.select("Role", ...) must now resolve and change it."""
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(form_01_url)
        await page.snapshot()
        await page.select("Role", "Engineer")
        result = await page._engine.send(
            "Runtime.evaluate",
            {"expression": "document.getElementById('role').value", "returnByValue": True},
        )
        assert result.get("result", {}).get("value") == "engineer"


@pytest.mark.asyncio
async def test_form_01_type_into_input_and_textarea_by_label(form_01_url):
    """Same fixture, same gap for the two other control kinds the fix covers:
    an <input> ("Full name") and a <textarea> ("Notes"), each named only by a
    sibling <label for=...>, no placeholder or aria-label to fall back on."""
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(form_01_url)
        await page.snapshot()
        await page.type("Full name", "Ada Lovelace")
        await page.type("Notes", "left-handed")
        state = await page._engine.send(
            "Runtime.evaluate",
            {"expression": "window.__bench_state()", "returnByValue": True},
        )
        value = state.get("result", {}).get("value", {})
        assert value.get("full_name") == "Ada Lovelace"
        assert value.get("notes") == "left-handed"
