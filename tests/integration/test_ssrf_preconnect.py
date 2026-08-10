"""
FIX 4 — end-to-end proof of the TOCTOU claim behind Fetch-domain interception:
Chrome is paused before it opens a socket, not merely told to stop after.

The unit tests in tests/unit/test_page.py prove the *wiring* — that a refused
URL is answered with Fetch.failRequest and never Fetch.continueRequest — using
a CDPEngine double with no real network underneath it. That proves grip
*decided* to refuse. It cannot prove Chromium never opened the TCP connection
in the first place; for that there has to be a real listener on the other end
and a real browser in front of it.

This uses a raw TCP listener (not an HTTP server) so a bare accept() is
enough to fail the test — a refusal that let the TCP handshake through but
never sent a request would still show up here, which an HTTP request log
would miss.
"""
import asyncio
import socket
import threading

import pytest
from grip.browser import Browser
from grip.errors.types import ErrorType
from grip.errors import GripError


class _TCPRecorder:
    """A bare listening socket that records every accepted connection and
    nothing else — no HTTP parsing, so it cannot itself refuse anything."""

    def __init__(self) -> None:
        self.accepted: list = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(5)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.accepted.append(addr)
            conn.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1)
        self._sock.close()


@pytest.fixture
def recorder():
    rec = _TCPRecorder()
    yield rec
    rec.close()


@pytest.mark.asyncio
async def test_direct_open_of_private_target_never_connects(recorder):
    """Browser.open() refuses a private-IP URL in Python, before any tab
    exists at all — the simplest case, and the floor the harder case below
    has to also clear."""
    async with Browser(headless=True) as browser:  # default policy: private refused
        with pytest.raises(GripError) as exc:
            await browser.open(f"http://127.0.0.1:{recorder.port}/")
        assert exc.value.error.type is ErrorType.NAVIGATION_REFUSED
    await asyncio.sleep(0.5)
    assert recorder.accepted == [], (
        f"navigation refused in Python still reached the listener: {recorder.accepted}"
    )


@pytest.mark.asyncio
async def test_post_load_fetch_to_private_target_never_connects(recorder):
    """The harder case, and the one that actually exercises Fetch-domain
    interception end to end: the tab is already up (about:blank, the one
    non-http URL the policy allows), restrictive policy still in force, and
    page JS — not grip — initiates the request. Fetch.enable has to pause it
    pre-connect for the listener to see zero accepts."""
    async with Browser(headless=True) as browser:  # default policy: private refused
        page = await browser.open("about:blank")
        await page._eval(
            f"fetch('http://127.0.0.1:{recorder.port}/', {{mode: 'no-cors'}})"
            f".catch(function () {{}})"
        )
        await asyncio.sleep(1.0)
    assert recorder.accepted == [], (
        f"page JS reached the listener despite a restrictive policy: {recorder.accepted}"
    )


@pytest.mark.asyncio
async def test_popup_to_private_target_never_connects(recorder):
    """FIX 1, end to end: window.open() used to create a second CDP target
    with zero policy enforcement on it. Confirms the chosen fix (block the
    popup target outright) actually stops the request a real Chrome would
    have made from it."""
    async with Browser(headless=True) as browser:  # default policy: private refused
        page = await browser.open("about:blank")
        await page._eval(
            f"window.open('http://127.0.0.1:{recorder.port}/')"
        )
        await asyncio.sleep(1.0)
    assert recorder.accepted == [], (
        f"a popup reached the listener despite a restrictive policy: {recorder.accepted}"
    )
