import asyncio
import json
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from grip.browser import Browser
from grip.cdp.engine import CDPEngine
from grip.errors import GripError
from grip.errors.types import ErrorType
from grip.page import Page
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
    await asyncio.gather(browser._connect(), ticker())
    assert len(ticks) == 5
    # An absolute wall-clock budget flakes on a loaded/2-core runner. What this
    # test actually cares about is that launch()'s blocking sleep(0.15) ran off
    # the event loop, so the ticker's own ~0.01s cadence never got starved —
    # checked via the gaps between consecutive ticks, not total elapsed time.
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    assert max(gaps) < 0.1, f"event loop was blocked during launch: gaps={gaps}"


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
    with pytest.raises(GripError, match="navigation refused") as exc:
        await browser.open("file:///etc/passwd")
    assert exc.value.error.type is ErrorType.NAVIGATION_REFUSED


@pytest.mark.asyncio
async def test_open_refuses_loopback_by_default(monkeypatch):
    monkeypatch.setattr(CDPEngine, "connect", _async_noop)
    browser = Browser(cdp_url="ws://localhost:9222/devtools/browser/abc")
    with pytest.raises(GripError, match="navigation refused") as exc:
        await browser.open("http://127.0.0.1:8080/admin")
    assert exc.value.error.type is ErrorType.NAVIGATION_REFUSED


@pytest.mark.asyncio
async def test_open_refuses_cloud_metadata_by_default(monkeypatch):
    monkeypatch.setattr(CDPEngine, "connect", _async_noop)
    browser = Browser(cdp_url="ws://localhost:9222/devtools/browser/abc")
    with pytest.raises(GripError, match="metadata") as exc:
        await browser.open("http://169.254.169.254/latest/meta-data/")
    assert exc.value.error.type is ErrorType.NAVIGATION_REFUSED


@pytest.mark.asyncio
async def test_a_bare_domain_still_reaches_the_policy_as_https(monkeypatch):
    """Scheme-defaulting runs first, so "example.com" must not bypass the check."""
    monkeypatch.setattr(CDPEngine, "connect", _async_noop)
    browser = Browser(cdp_url="ws://localhost:9222/devtools/browser/abc")
    assert browser._policy.check("https://example.com") is None
    with pytest.raises(GripError, match="navigation refused") as exc:
        await browser.open("localhost:3000")
    assert exc.value.error.type is ErrorType.NAVIGATION_REFUSED


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


@pytest.mark.asyncio
async def test_pages_property_and_get_page_track_open_and_closed_tabs():
    browser = Browser()
    engine = MagicMock()
    engine.send = AsyncMock(return_value={})
    browser._engine = engine

    class _Stub:
        def __init__(self, target_id):
            self._target_id = target_id

    p1, p2 = _Stub("T1"), _Stub("T2")
    browser._pages = [p1, p2]

    assert browser.pages == (p1, p2)
    assert browser.get_page("T2") is p2
    assert browser.get_page("nope") is None

    await browser._close_target("T1")
    assert browser.pages == (p2,)
    assert browser.get_page("T1") is None


@pytest.mark.asyncio
async def test_each_tab_gets_its_own_fetch_interception_armed(monkeypatch):
    """Fetch interception is armed per-Page inside goto() -> _ensure_initialized
    (see grip/page.py). A second tab opened through Browser.open() must arm it
    on its OWN CDP session — most tests here pin every CDPEngine() instantiation
    to the same MagicMock (MockEngine.return_value = engine), which would let a
    per-tab regression (e.g. arming only tab 1) pass unnoticed. side_effect
    gives each call to CDPEngine() a genuinely distinct object instead."""
    browser_engine = MagicMock()
    browser_engine.connect = AsyncMock()
    browser_engine.send = AsyncMock(side_effect=[
        {"targetId": "T1"},  # Target.createTarget, tab 1
        {"targetId": "T2"},  # Target.createTarget, tab 2
    ])

    page_engines: list[MagicMock] = []

    def _new_page_engine() -> MagicMock:
        eng = MagicMock()
        eng.connect = AsyncMock()
        eng.on = MagicMock()
        eng.send = AsyncMock(return_value={})
        page_engines.append(eng)
        return eng

    engines = iter([browser_engine, _new_page_engine(), _new_page_engine()])
    monkeypatch.setattr("grip.browser.CDPEngine", lambda: next(engines))

    async def fake_goto(self, url, timeout=30.0):
        # Real goto() waits on page-load CDP events this mock never fires.
        # What's under test is "opening a tab arms interception on that tab's
        # own session" — goto()'s navigation-wait machinery is covered in
        # tests/unit/test_page.py, not here.
        await self._ensure_initialized()
        self._current_url = url

    monkeypatch.setattr(Page, "goto", fake_goto)

    browser = Browser(cdp_url="ws://localhost:9222/devtools/browser/abc")
    page1 = await browser.open("https://a.test")
    page2 = await browser.open("https://b.test")

    assert page1._engine is page_engines[0]
    assert page2._engine is page_engines[1]
    assert page1._engine is not page2._engine

    def _fetch_enable_calls(eng: MagicMock) -> list[object]:
        return [c for c in eng.send.call_args_list if c.args[0] == "Fetch.enable"]

    assert _fetch_enable_calls(page_engines[0]), "tab 1 must have interception armed"
    assert _fetch_enable_calls(page_engines[1]), (
        "tab 2 must have interception armed on its own session, not skipped"
    )


@pytest.mark.asyncio
async def test_save_session_captures_cookies_and_per_origin_localstorage(tmp_path):
    browser = Browser()

    async def browser_send(method, params=None):
        if method == "Storage.getCookies":
            return {"cookies": [{"name": "sid", "value": "abc", "domain": "a.test"}]}
        if method == "Target.getTargetInfo":
            return {"targetInfo": {"url": "https://a.test/page"}}
        raise AssertionError(f"unexpected browser-level call {method}")

    engine = MagicMock()
    engine.send = AsyncMock(side_effect=browser_send)
    browser._engine = engine

    async def page_send(method, params=None):
        assert method == "Runtime.evaluate"
        return {"result": {"value": json.dumps({"token": "xyz"})}}

    page_engine = MagicMock()
    page_engine.send = AsyncMock(side_effect=page_send)

    class _Stub:
        _target_id = "T1"
        _engine = page_engine

    browser._pages = [_Stub()]

    session_path = tmp_path / "session.json"
    await browser.save_session(str(session_path))

    data = json.loads(session_path.read_text())
    assert data["cookies"] == [{"name": "sid", "value": "abc", "domain": "a.test"}]
    assert data["origins"] == {"https://a.test": {"localStorage": {"token": "xyz"}}}
    assert oct(session_path.stat().st_mode & 0o777) == oct(0o600)


@pytest.mark.asyncio
async def test_load_session_reads_the_old_cookie_only_format(tmp_path):
    """Session files predate the {"cookies", "origins"} shape — a bare cookie
    list must still load. The list-vs-dict shape is the only version marker
    an old file can have, so that's what detects it."""
    browser = Browser()
    calls = []

    async def browser_send(method, params=None):
        calls.append((method, params))
        return {}

    engine = MagicMock()
    engine.send = AsyncMock(side_effect=browser_send)
    browser._engine = engine

    session_path = tmp_path / "old_session.json"
    old_cookies = [{"name": "sid", "value": "abc", "domain": "a.test"}]
    session_path.write_text(json.dumps(old_cookies))

    await browser.load_session(str(session_path))

    assert calls == [("Storage.setCookies", {"cookies": old_cookies})]


@pytest.mark.asyncio
async def test_load_session_restores_localstorage_into_a_matching_open_tab(tmp_path):
    browser = Browser()

    async def browser_send(method, params=None):
        if method == "Storage.setCookies":
            return {}
        if method == "Target.getTargetInfo":
            return {"targetInfo": {"url": "https://a.test/dashboard"}}
        raise AssertionError(f"unexpected browser-level call {method}")

    engine = MagicMock()
    engine.send = AsyncMock(side_effect=browser_send)
    browser._engine = engine

    seen_exprs = []

    async def page_send(method, params=None):
        assert method == "Runtime.evaluate"
        seen_exprs.append(params["expression"])
        return {}

    page_engine = MagicMock()
    page_engine.send = AsyncMock(side_effect=page_send)

    class _Stub:
        _target_id = "T1"
        _engine = page_engine

        async def close(self):
            raise AssertionError("must not close a tab it did not open")

    browser._pages = [_Stub()]

    session_path = tmp_path / "session.json"
    session_path.write_text(json.dumps(
        {"cookies": [], "origins": {"https://a.test": {"localStorage": {"k": "v"}}}}
    ))

    await browser.load_session(str(session_path))

    assert seen_exprs, "must have written localStorage into the matching open tab"
    assert "localStorage.setItem" in seen_exprs[0]
    assert '"k"' in seen_exprs[0] and '"v"' in seen_exprs[0]
