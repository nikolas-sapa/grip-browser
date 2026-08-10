import json
import pytest
import tempfile
import os
from unittest.mock import AsyncMock, MagicMock, patch
from grip.browser import Browser


def _make_browser_with_engine(send_side_effect):
    # A real Browser(): cheap here (no Chrome launch, nothing but field
    # defaults) and it can't drift from the constructor the way the old
    # Browser.__new__(Browser) + hand-picked attributes did — that hand-built
    # object was missing _pages entirely and broke silently the moment
    # save_session started reading it.
    browser = Browser()
    engine = MagicMock()
    engine.send = AsyncMock(side_effect=send_side_effect)
    browser._engine = engine
    return browser


@pytest.mark.asyncio
async def test_save_session_writes_cookies():
    cookies = [
        {"name": "session", "value": "abc123", "domain": "example.com",
         "path": "/", "expires": -1, "size": 14, "httpOnly": True,
         "secure": True, "session": True, "sameSite": "None"}
    ]
    # save_session now iterates browser.pages to find localStorage origins;
    # with no open tabs the send side effects are still just the one
    # Storage.getCookies call this list has always had.
    browser = _make_browser_with_engine([{"cookies": cookies}])
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        await browser.save_session(path)
        with open(path) as f:
            saved = json.load(f)
        # Session files are now {"cookies": [...], "origins": {...}} rather
        # than a bare cookie list, to carry per-origin localStorage alongside
        # cookies. No open tabs means no origins captured.
        assert saved == {"cookies": cookies, "origins": {}}
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_load_session_sends_set_cookies():
    cookies = [
        {"name": "session", "value": "abc123", "domain": "example.com",
         "path": "/", "expires": -1, "size": 14, "httpOnly": True,
         "secure": True, "session": True, "sameSite": "None"}
    ]
    browser = _make_browser_with_engine([{}])  # Storage.setCookies
    # `cookies` is dumped as a bare list, not {"cookies": ..., "origins": ...}
    # — this is the pre-existing on-disk format, and this test is exactly the
    # backward-compat path: an old session file must still load.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(cookies, f)
        path = f.name
    try:
        await browser.load_session(path)
        calls = browser._engine.send.call_args_list
        methods = [c[0][0] for c in calls]
        assert "Storage.setCookies" in methods
        set_cookies_call = next(c for c in calls if c[0][0] == "Storage.setCookies")
        assert set_cookies_call[0][1]["cookies"] == cookies
    finally:
        os.unlink(path)
