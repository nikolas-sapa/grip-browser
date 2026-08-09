import asyncio
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from grip.browser import Browser
from grip.cdp.engine import CDPEngine
from grip.trace import Trace


def _async_return(value):
    async def _inner(*args, **kwargs):
        # A real suspension point: without one the fake never yields to the loop and
        # concurrent _connect() calls would serialize by accident, not by design.
        await asyncio.sleep(0)
        return value
    return _inner


async def _async_noop(*args, **kwargs):
    return None


@pytest.mark.asyncio
async def test_browser_creates_trace():
    with patch("grip.browser.ChromeLauncher") as MockLauncher, \
         patch("grip.browser.CDPEngine") as MockEngine, \
         patch("grip.browser.fetch_browser_ws_url", new_callable=AsyncMock) as mock_fetch:
        launcher = MagicMock()
        launcher.launch.return_value = 9222
        launcher.terminate = MagicMock()
        launcher.aterminate = AsyncMock()
        MockLauncher.return_value = launcher

        engine = MagicMock()
        engine.connect = AsyncMock()
        engine.disconnect = AsyncMock()
        engine.send = AsyncMock(return_value={"targetInfos": []})
        MockEngine.return_value = engine

        mock_fetch.return_value = "ws://localhost:9222/devtools/browser/abc"

        browser = Browser()
        assert isinstance(browser.trace, Trace)


@pytest.mark.asyncio
async def test_browser_context_manager():
    with patch("grip.browser.ChromeLauncher") as MockLauncher, \
         patch("grip.browser.CDPEngine") as MockEngine, \
         patch("grip.browser.fetch_browser_ws_url", new_callable=AsyncMock) as mock_fetch:
        launcher = MagicMock()
        launcher.launch.return_value = 9222
        launcher.terminate = MagicMock()
        launcher.aterminate = AsyncMock()
        MockLauncher.return_value = launcher

        engine = MagicMock()
        engine.connect = AsyncMock()
        engine.disconnect = AsyncMock()
        engine.send = AsyncMock(return_value={"targetInfos": []})
        MockEngine.return_value = engine

        mock_fetch.return_value = "ws://localhost:9222/devtools/browser/abc"

        async with Browser() as browser:
            assert browser is not None


@pytest.mark.asyncio
async def test_concurrent_connect_launches_one_chrome(monkeypatch):
    launches = []

    class FakeLauncher:
        port = 9222

        def launch(self, **kwargs):
            launches.append(1)
            return 9222

        def terminate(self):
            pass

    monkeypatch.setattr("grip.browser.ChromeLauncher", FakeLauncher)
    monkeypatch.setattr("grip.browser.fetch_browser_ws_url", _async_return("ws://x"))
    monkeypatch.setattr(CDPEngine, "connect", _async_noop)

    browser = Browser()
    await asyncio.gather(*(browser._connect() for _ in range(4)))
    assert len(launches) == 1


@pytest.mark.asyncio
async def test_connect_failure_terminates_chrome(monkeypatch):
    terminated = []

    class FakeLauncher:
        port = 9222

        def launch(self, **kwargs):
            return 9222

        def terminate(self):
            terminated.append(1)

    async def boom(port):
        raise RuntimeError("no endpoint")

    monkeypatch.setattr("grip.browser.ChromeLauncher", FakeLauncher)
    monkeypatch.setattr("grip.browser.fetch_browser_ws_url", boom)

    browser = Browser()
    with pytest.raises(RuntimeError):
        await browser._connect()
    assert terminated == [1], "Chrome was left running after a failed connect"


@pytest.mark.asyncio
async def test_close_terminates_chrome_even_if_disconnect_raises():
    terminated = []

    class FakeLauncher:
        def terminate(self):
            terminated.append(1)

        async def aterminate(self):
            self.terminate()

    class BadEngine:
        async def disconnect(self):
            raise RuntimeError("socket already gone")

    browser = Browser()
    browser._engine = BadEngine()
    browser._launcher = FakeLauncher()
    await browser.close()
    assert terminated == [1], "a failing disconnect skipped launcher teardown"


@pytest.mark.asyncio
async def test_launch_runs_off_the_event_loop(monkeypatch):
    """A 10s port poll inside launch() must not freeze concurrent tasks."""
    import grip.browser as bmod

    ticks = []

    async def ticker():
        for _ in range(5):
            # Timestamps, not a count: gather() waits for the ticker either way, so
            # only *when* the ticks land distinguishes a blocked loop from a free one.
            ticks.append(time.monotonic())
            await asyncio.sleep(0.01)

    class SlowLauncher:
        port = 9222

        def launch(self, **kwargs):
            time.sleep(0.15)
            return 9222

        def terminate(self):
            pass

    monkeypatch.setattr(bmod, "ChromeLauncher", SlowLauncher)
    monkeypatch.setattr(bmod, "fetch_browser_ws_url", _async_return("ws://x"))
    monkeypatch.setattr(CDPEngine, "connect", _async_noop)

    browser = Browser()
    start = time.monotonic()
    await asyncio.gather(browser._connect(), ticker())
    assert len(ticks) == 5
    assert ticks[-1] - start < 0.12, "event loop was blocked during launch"
