import pytest
from unittest.mock import AsyncMock, MagicMock
from grip.page import Page
from grip.trace import Trace
from grip.errors.types import GripError, ErrorType


def _make_safe_page():
    engine = MagicMock()
    engine.send = AsyncMock(return_value={})
    return Page(engine=engine, trace=Trace(), safe=True)


@pytest.mark.asyncio
async def test_safe_mode_blocks_click():
    page = _make_safe_page()
    with pytest.raises(GripError) as exc:
        await page.click("Buy Now")
    assert exc.value.error.type == ErrorType.SAFE_MODE_VIOLATION


@pytest.mark.asyncio
async def test_safe_mode_blocks_type():
    page = _make_safe_page()
    with pytest.raises(GripError) as exc:
        await page.type("search", "hello")
    assert exc.value.error.type == ErrorType.SAFE_MODE_VIOLATION


@pytest.mark.asyncio
async def test_safe_mode_blocks_press():
    page = _make_safe_page()
    with pytest.raises(GripError) as exc:
        await page.press("Enter")
    assert exc.value.error.type == ErrorType.SAFE_MODE_VIOLATION


@pytest.mark.asyncio
async def test_safe_mode_allows_snapshot():
    page = _make_safe_page()
    page._engine.send.side_effect = [
        {}, {},
        {"result": {"value": "[]"}},
        {"result": {"value": ""}},
        {"targetInfo": {"title": "Test", "url": "https://example.com"}},
    ]
    snap = await page.snapshot()  # should not raise
    assert snap is not None
