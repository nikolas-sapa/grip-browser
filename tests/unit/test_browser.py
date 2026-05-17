import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from grip.browser import Browser
from grip.trace import Trace


@pytest.mark.asyncio
async def test_browser_creates_trace():
    with patch("grip.browser.ChromeLauncher") as MockLauncher, \
         patch("grip.browser.CDPEngine") as MockEngine, \
         patch("grip.browser.fetch_tab_ws_url", new_callable=AsyncMock) as mock_fetch:
        launcher = MagicMock()
        launcher.launch.return_value = 9222
        launcher.terminate = MagicMock()
        MockLauncher.return_value = launcher

        engine = MagicMock()
        engine.connect = AsyncMock()
        engine.disconnect = AsyncMock()
        engine.send = AsyncMock(return_value={"targetInfos": []})
        MockEngine.return_value = engine

        mock_fetch.return_value = "ws://localhost:9222/devtools/page/abc"

        browser = Browser()
        assert isinstance(browser.trace, Trace)


@pytest.mark.asyncio
async def test_browser_context_manager():
    with patch("grip.browser.ChromeLauncher") as MockLauncher, \
         patch("grip.browser.CDPEngine") as MockEngine, \
         patch("grip.browser.fetch_tab_ws_url", new_callable=AsyncMock) as mock_fetch:
        launcher = MagicMock()
        launcher.launch.return_value = 9222
        launcher.terminate = MagicMock()
        MockLauncher.return_value = launcher

        engine = MagicMock()
        engine.connect = AsyncMock()
        engine.disconnect = AsyncMock()
        engine.send = AsyncMock(return_value={"targetInfos": []})
        MockEngine.return_value = engine

        mock_fetch.return_value = "ws://localhost:9222/devtools/page/abc"

        async with Browser() as browser:
            assert browser is not None
