from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from grip.page import Page
from grip.errors.types import ErrorType
from grip.trace import Trace


def _make_page():
    engine = MagicMock()
    engine.send = AsyncMock()
    return Page(engine=engine, trace=Trace())


def test_page_snapshot_has_page_error_field():
    from grip.compression.summarizer import PageSnapshot
    snap = PageSnapshot(
        version=1, url="https://example.com", title="Test",
        elements=[], text_content="hello", tokens_estimated=5,
    )
    assert snap.page_error is None


@pytest.mark.asyncio
async def test_snapshot_detects_bot_block():
    page = _make_page()
    page._engine.send.side_effect = [
        # Runtime.enable
        {},
        # Page.enable
        {},
        # DISCOVER_ELEMENTS_JS
        {"result": {"value": "[]"}},
        # PAGE_TEXT_JS
        {"result": {"value": "Access denied"}},
        # Target.getTargetInfo
        {"targetInfo": {"title": "Access Denied | Cloudflare", "url": "https://example.com/blocked"}},
    ]
    snapshot = await page.snapshot()
    assert snapshot.page_error is not None
    assert snapshot.page_error.type == ErrorType.ANTI_BOT_BLOCK


@pytest.mark.asyncio
async def test_snapshot_page_error_none_on_normal_page():
    page = _make_page()
    page._engine.send.side_effect = [
        {}, {},
        {"result": {"value": "[]"}},
        {"result": {"value": "Hello world"}},
        {"targetInfo": {"title": "Example Domain", "url": "https://example.com"}},
    ]
    snapshot = await page.snapshot()
    assert snapshot.page_error is None
