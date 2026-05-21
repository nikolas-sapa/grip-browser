import json
import pytest
import tempfile
import os
from unittest.mock import AsyncMock, MagicMock, patch
from grip.browser import Browser


def _make_browser_with_engine(send_side_effect):
    browser = Browser.__new__(Browser)
    browser._llm = None
    browser._headless = True
    browser._safe = False
    browser._proxy = None
    browser._launcher = None
    from grip.trace import Trace
    browser.trace = Trace()
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
    browser = _make_browser_with_engine([{"cookies": cookies}])
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        await browser.save_session(path)
        with open(path) as f:
            saved = json.load(f)
        assert saved == cookies
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_load_session_sends_set_cookies():
    cookies = [
        {"name": "session", "value": "abc123", "domain": "example.com",
         "path": "/", "expires": -1, "size": 14, "httpOnly": True,
         "secure": True, "session": True, "sameSite": "None"}
    ]
    browser = _make_browser_with_engine([{}, {}])  # Network.enable, Network.setCookies
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(cookies, f)
        path = f.name
    try:
        await browser.load_session(path)
        calls = browser._engine.send.call_args_list
        methods = [c[0][0] for c in calls]
        assert "Network.enable" in methods
        assert "Network.setCookies" in methods
        set_cookies_call = next(c for c in calls if c[0][0] == "Network.setCookies")
        assert set_cookies_call[0][1]["cookies"] == cookies
    finally:
        os.unlink(path)
