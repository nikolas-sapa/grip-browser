import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from grip.page import Page
from grip.cdp.engine import CDPEngine
from grip.trace import Trace


def make_cdp_mock():
    engine = MagicMock(spec=CDPEngine)
    engine.send = AsyncMock()
    engine.on = MagicMock()
    engine.off = MagicMock()
    return engine


@pytest.mark.asyncio
async def test_snapshot_returns_page_snapshot():
    engine = make_cdp_mock()
    engine.send.side_effect = [
        {},   # Runtime.enable
        {},   # Page.enable
        {"result": {"value": json.dumps([
            {
                "index": 0, "tag": "button", "role": "button", "text": "Buy",
                "placeholder": None, "inShadowDom": False,
                "cx": 100, "cy": 50,
                "computedDisplay": "block", "computedVisibility": "visible",
                "computedOpacity": "1", "ariaHidden": False, "width": 80, "height": 30,
            }
        ])}},
        {"result": {"value": "Buy our products"}},
        {"targetInfo": {"title": "Shop", "url": "https://shop.com"}},
    ]
    page = Page(engine=engine, trace=Trace())
    snapshot = await page.snapshot()
    assert snapshot.url == "https://shop.com"
    assert len(snapshot.elements) == 1
    assert snapshot.elements[0].text == "Buy"


@pytest.mark.asyncio
async def test_snapshot_increments_version():
    engine = make_cdp_mock()
    engine.send.side_effect = [
        {},
        {},
        {"result": {"value": "[]"}},
        {"result": {"value": ""}},
        {"targetInfo": {"title": "X", "url": "https://x.com"}},
        {"result": {"value": "[]"}},
        {"result": {"value": ""}},
        {"targetInfo": {"title": "X", "url": "https://x.com"}},
    ]
    page = Page(engine=engine, trace=Trace())
    s1 = await page.snapshot()
    s2 = await page.snapshot()
    assert s2.version == s1.version + 1
