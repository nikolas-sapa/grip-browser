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
        launch_timeout = 10.0

        def __init__(self, user_data_dir=None, launch_timeout=None):
            pass

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
        launch_timeout = 10.0

        def __init__(self, user_data_dir=None, launch_timeout=None):
            pass

        def launch(self, **kwargs):
            return 9222

        def terminate(self):
            terminated.append(1)

    async def boom(port, timeout=None):
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
        launch_timeout = 10.0

        def __init__(self, user_data_dir=None, launch_timeout=None):
            pass

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


@pytest.mark.asyncio
async def test_cdp_url_skips_launching_chrome(monkeypatch):
    launched = []

    class FakeLauncher:
        port = 9222
        launch_timeout = 10.0

        def launch(self, **kwargs):
            launched.append(1)
            return 9222

        def terminate(self):
            pass

    monkeypatch.setattr("grip.browser.ChromeLauncher", FakeLauncher)
    monkeypatch.setattr(CDPEngine, "connect", _async_noop)

    browser = Browser(cdp_url="ws://localhost:9222/devtools/browser/abc")
    await browser._connect()
    assert launched == [], "cdp_url should attach, not launch"
    assert browser._launcher is None, "attached mode must own no Chrome to terminate"


@pytest.mark.asyncio
async def test_cdp_url_accepts_a_remote_wss_endpoint(monkeypatch):
    """A remote CDP engine (Kitesurf on Workers, a browser-grid vendor) is a wss://
    URL on someone else's host, usually carrying an auth token in the query."""
    connected = []

    async def record_connect(self, url):
        connected.append(url)

    monkeypatch.setattr(CDPEngine, "connect", record_connect)

    remote = "wss://kitesurf.example.workers.dev/v1/browser/abc?token=t0ken"
    browser = Browser(cdp_url=remote)
    await browser._connect()
    assert connected == [remote]

    page_url = browser._page_ws_url("TARGET123")
    assert page_url.startswith("wss://kitesurf.example.workers.dev/")
    assert "localhost" not in page_url
    assert page_url.endswith("/devtools/page/TARGET123?token=t0ken")


def test_page_ws_url_uses_the_local_port_when_we_launched(monkeypatch):
    browser = Browser()
    browser._port = 9333
    assert browser._page_ws_url("T1") == "ws://localhost:9333/devtools/page/T1"


@pytest.mark.asyncio
async def test_open_refuses_a_file_url_by_default(monkeypatch):
    """Local file reads are the other half of the SSRF hole: open("file:///etc/passwd")
    used to come straight back through read()."""
    monkeypatch.setattr(CDPEngine, "connect", _async_noop)
    browser = Browser(cdp_url="ws://localhost:9222/devtools/browser/abc")
    with pytest.raises(ValueError, match="navigation refused"):
        await browser.open("file:///etc/passwd")


@pytest.mark.asyncio
async def test_open_refuses_loopback_by_default(monkeypatch):
    monkeypatch.setattr(CDPEngine, "connect", _async_noop)
    browser = Browser(cdp_url="ws://localhost:9222/devtools/browser/abc")
    with pytest.raises(ValueError, match="navigation refused"):
        await browser.open("http://127.0.0.1:8080/admin")


@pytest.mark.asyncio
async def test_open_refuses_cloud_metadata_by_default(monkeypatch):
    monkeypatch.setattr(CDPEngine, "connect", _async_noop)
    browser = Browser(cdp_url="ws://localhost:9222/devtools/browser/abc")
    with pytest.raises(ValueError, match="metadata"):
        await browser.open("http://169.254.169.254/latest/meta-data/")


@pytest.mark.asyncio
async def test_a_bare_domain_still_reaches_the_policy_as_https(monkeypatch):
    """Scheme-defaulting runs first, so "example.com" must not bypass the check."""
    monkeypatch.setattr(CDPEngine, "connect", _async_noop)
    browser = Browser(cdp_url="ws://localhost:9222/devtools/browser/abc")
    assert browser._policy.check("https://example.com") is None
    with pytest.raises(ValueError, match="navigation refused"):
        await browser.open("localhost:3000")


@pytest.mark.asyncio
async def test_user_data_dir_reaches_the_launcher(monkeypatch):
    """Without this the launcher can support profiles while Browser silently
    drops the argument, and every "persistent" run gets a fresh temp profile."""
    seen = {}

    class RecordingLauncher:
        port = 9222
        launch_timeout = 10.0

        def __init__(self, user_data_dir=None, launch_timeout=None):
            seen["dir"] = user_data_dir

        def launch(self, **kwargs):
            return 9222

        def terminate(self):
            pass

    monkeypatch.setattr("grip.browser.ChromeLauncher", RecordingLauncher)
    monkeypatch.setattr("grip.browser.fetch_browser_ws_url", _async_return("ws://x"))
    monkeypatch.setattr(CDPEngine, "connect", _async_noop)

    await Browser(user_data_dir="/tmp/grip_profile_x")._connect()
    assert seen["dir"] == "/tmp/grip_profile_x"


def test_page_ws_url_keeps_a_non_default_remote_port():
    browser = Browser(cdp_url="wss://cdp.example.net:7443/session/abc?token=t0ken")
    assert browser._page_ws_url("T9") == (
        "wss://cdp.example.net:7443/devtools/page/T9?token=t0ken"
    )
