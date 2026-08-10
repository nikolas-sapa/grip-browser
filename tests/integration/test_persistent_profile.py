"""Cookie JSON cannot carry localStorage, IndexedDB or service workers; a reused
profile directory carries all of it for free."""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from grip.browser import Browser

_PAGE = b"<html><head><title>Example Domain</title></head><body><p>ok</p></body></html>"


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
async def test_local_storage_survives_a_restart(tmp_path, base_url):
    profile = str(tmp_path / "profile")

    async with Browser(user_data_dir=profile, allow_private=True) as browser:
        page = await browser.open(base_url)
        await page._engine.send("Runtime.evaluate", {
            "expression": "localStorage.setItem('grip_test', 'kept')"
        })

    async with Browser(user_data_dir=profile, allow_private=True) as browser:
        page = await browser.open(base_url)
        result = await page._engine.send("Runtime.evaluate", {
            "expression": "localStorage.getItem('grip_test')", "returnByValue": True
        })
        assert result["result"]["value"] == "kept"


@pytest.mark.asyncio
async def test_a_caller_profile_outlives_the_browser(tmp_path, base_url):
    """The whole point of passing user_data_dir is that it is still there next run."""
    profile = tmp_path / "profile"

    async with Browser(user_data_dir=str(profile), allow_private=True) as browser:
        await browser.open(base_url)

    assert profile.exists(), "grip deleted a profile directory it did not create"
    assert any(profile.iterdir()), "profile directory is empty — Chrome never used it"
