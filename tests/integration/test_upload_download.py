"""
Real Chrome integration test for page.upload()/enable_downloads()/
wait_for_download(): proves an actual file round-trips through a local
http.server fixture (no network dependency in CI).

Run: .venv/bin/python3 -m pytest tests/integration/test_upload_download.py -v -s
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from grip.browser import Browser

_DOWNLOAD_BYTES = b"grip integration test download payload\n" * 100


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            body = (
                b"<html><body>"
                b'<label for="cv">Resume field</label>'
                b'<input id="cv" type="file" multiple>'
                b'<a href="/report.bin" id="dl">Download report</a>'
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/report.bin":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header(
                "Content-Disposition", 'attachment; filename="report.bin"'
            )
            self.send_header("Content-Length", str(len(_DOWNLOAD_BYTES)))
            self.end_headers()
            self.wfile.write(_DOWNLOAD_BYTES)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def base_url():
    # Loopback fixture: NavigationPolicy refuses private addresses by default
    # (SSRF guard), so this Browser opts in with allow_private=True — same
    # pattern as tests/integration/test_real_browser.py.
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}/"
    httpd.shutdown()


@pytest.mark.asyncio
async def test_upload_and_download_round_trip(base_url, tmp_path):
    upload_file = tmp_path / "resume.pdf"
    upload_file.write_bytes(b"grip integration test resume bytes")
    download_dir = tmp_path / "downloads"

    async with Browser(headless=True, allow_private=True) as browser:
        page = await browser.open(base_url)

        # Upload: real DOM.setFileInputFiles against a real <input type=file>,
        # resolved by the label text a form would actually carry.
        await page.upload("resume field", str(upload_file))
        uploaded_name = await page._eval(
            "document.getElementById('cv').files[0].name"
        )
        assert uploaded_name == upload_file.name

        # Download: click a real link that responds with
        # Content-Disposition: attachment, and await the file landing on disk.
        await page.enable_downloads(download_dir)
        await page.click("download report")
        downloaded_path = await page.wait_for_download(timeout=15)

        assert downloaded_path.exists()
        assert downloaded_path.read_bytes() == _DOWNLOAD_BYTES
        assert downloaded_path.parent == download_dir.resolve()
