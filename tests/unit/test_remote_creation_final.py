import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from grip.browser import Browser
from grip.cdp.engine import CDPEngine


@pytest.mark.asyncio
async def test_cancelled_creation_preserves_cancellation_when_command_fails():
    browser = Browser()
    root = MagicMock(spec=CDPEngine)
    browser._engine = root
    browser._connect = AsyncMock()
    browser._ensure_popup_routing = AsyncMock()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def fail_creation(*args):
        entered.set()
        await release.wait()
        raise RuntimeError("target creation failed")

    root.send = AsyncMock(side_effect=fail_creation)
    opening = asyncio.create_task(browser.open("about:blank"))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        opening.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(opening, 1)
        assert browser.pages == ()
        root.send.assert_awaited_once_with("Target.createTarget", {"url": "about:blank"})
    finally:
        release.set()
        if not opening.done():
            opening.cancel()
        await asyncio.gather(opening, return_exceptions=True)


@pytest.mark.asyncio
async def test_concurrent_open_waits_for_remote_setup_readiness():
    browser = Browser(cdp_url="ws://fixture")
    root = MagicMock(spec=CDPEngine)
    root.connect = AsyncMock()
    root.disconnect = AsyncMock()
    root.send = AsyncMock()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def permissions(engine):
        entered.set()
        await release.wait()

    browser._apply_permissions = permissions
    browser._resolve_stealth_ua = AsyncMock()
    with patch("grip.browser.CDPEngine", return_value=root):
        connecting = asyncio.create_task(browser._connect())
        opening = None
        try:
            await asyncio.wait_for(entered.wait(), 1)
            opening = asyncio.create_task(browser.open("about:blank"))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            root.send.assert_not_awaited()
            assert not opening.done()
        finally:
            if opening is not None:
                opening.cancel()
                await asyncio.gather(opening, return_exceptions=True)
            release.set()
            await connecting
            await browser.close()


@pytest.mark.asyncio
async def test_failed_remote_setup_retains_failed_disconnect_for_explicit_retry():
    browser = Browser(cdp_url="ws://fixture")
    root = MagicMock(spec=CDPEngine)
    root.connect = AsyncMock()
    root.disconnect = AsyncMock(side_effect=[RuntimeError("close failed"),
                                            RuntimeError("retry failed"), None])
    browser._apply_permissions = AsyncMock(side_effect=ValueError("setup failed"))
    with patch("grip.browser.CDPEngine", return_value=root):
        with pytest.raises(ValueError, match="setup failed"):
            await browser._connect()
        assert browser._engine is root
        assert browser._remote_setup_incomplete
        with pytest.raises(RuntimeError, match="Close before reconnecting"):
            await browser.open("about:blank")
        root.send.assert_not_called()
        with pytest.raises(RuntimeError, match="retry failed"):
            await browser.close()
        assert browser._engine is root
        assert browser._remote_setup_incomplete
        await browser.close()
        assert browser._engine is None
        assert not browser._remote_setup_incomplete
        assert root.disconnect.await_count == 3
