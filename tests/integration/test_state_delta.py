"""State-only transitions through real Chrome, snapshot deltas and payloads."""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from grip.browser import Browser
from grip.compression.delta import format_delta
from grip.compression.summarizer import Summarizer


_PAGE = ("""<!doctype html><html><head><title>State delta</title></head><body>
<label><input id="check" type="checkbox">Check</label>
<input id="field" placeholder="Field">
<button id="button">Action</button>
<button id="choice" aria-selected="false">Choice</button>
<select id="select"><option value="alpha">Alpha</option><option value="beta">Beta</option></select>
<button id="combo" role="combobox" aria-expanded="false">Choose</button>
<p>""" + " ".join(f"stable{i}" for i in range(180)) + "</p></body></html>").encode()


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
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.asyncio
@pytest.mark.parametrize("element_id,activate,reset,field,active", [
    ("check", "el.checked = true", "el.checked = false", "checked", True),
    ("field", "el.value = 'typed'", "el.value = ''", "value", "typed"),
    ("button", "el.disabled = true", "el.disabled = false", "disabled", True),
    ("select", "el.value = 'beta'", "el.value = 'alpha'", "value", "Beta"),
    ("choice", "el.setAttribute('aria-selected', 'true')",
     "el.setAttribute('aria-selected', 'false')", "selected", True),
    ("combo", "el.setAttribute('aria-expanded', 'true')",
     "el.setAttribute('aria-expanded', 'false')", "combobox_expanded", True),
])
async def test_state_only_transitions_reach_delta_and_payload(
    base_url, element_id, activate, reset, field, active
):
    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)
        baseline = await page.snapshot()
        _, sent_version = page.payload(0)
        # Obtain Grip's own stable handle, so assertions address the exact node.
        result = await page._engine.send("Runtime.evaluate", {
            "expression": f"document.getElementById('{element_id}').getAttribute('data-grip-h')",
            "returnByValue": True,
        })
        handle = result["result"]["value"]
        before = next(el for el in baseline.elements if el.handle == handle)
        inactive = getattr(before, field)
        for script, expected in ((activate, active), (reset, inactive)):
            await page._engine.send("Runtime.evaluate", {
                "expression": (
                    f"(() => {{ const el = document.getElementById('{element_id}'); "
                    f"{script}; }})()"
                ),
                "returnByValue": True,
            })
            snapshot = await page.snapshot()
            after = next(el for el in snapshot.elements if el.handle == handle)
            assert getattr(after, field) == expected
            # Input values also participate in the accessible label; the other
            # controls prove state changes with exactly unchanged text.
            if element_id != "field":
                assert after.text == before.text
            assert snapshot.text_content == baseline.text_content
            assert snapshot.changed_from_previous
            delta = page.delta
            assert delta is not None and not delta.is_empty
            assert delta.content_ops == [] and not delta.added and not delta.removed
            changes = [change for change in delta.changed if change[0] == after.ref]
            assert len(changes) == 1
            _, old, new = changes[0]
            assert old != new
            assert Summarizer._element_state_suffix(before) in old
            assert Summarizer._element_state_suffix(after) in new
            payload, sent_version = page.payload(sent_version)
            assert payload == format_delta(delta)
            assert "no change" not in payload and f"~ [{after.ref}]" in payload
            assert sent_version == snapshot.version
            before = after
        unchanged = await page.snapshot()
        assert not unchanged.changed_from_previous
        assert page.delta is not None and page.delta.is_empty
        payload, version = page.payload(sent_version)
        assert payload == format_delta(page.delta) and "no change" in payload
        assert version == unchanged.version
