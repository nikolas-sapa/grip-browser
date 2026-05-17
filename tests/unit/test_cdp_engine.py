import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from grip.cdp.engine import CDPEngine


@pytest.fixture
def mock_ws():
    ws = AsyncMock()
    ws.send = AsyncMock()
    ws.recv = AsyncMock(return_value=json.dumps({"id": 1, "result": {"nodeId": 42}}))
    ws.__aenter__ = AsyncMock(return_value=ws)
    ws.__aexit__ = AsyncMock(return_value=False)
    return ws


@pytest.mark.asyncio
async def test_send_returns_result(mock_ws):
    engine = CDPEngine.__new__(CDPEngine)
    engine._ws = mock_ws
    engine._id = 0
    engine._pending = {}
    engine._listeners = {}

    async def fake_send(msg_str):
        msg = json.loads(msg_str)
        fut = engine._pending.get(msg["id"])
        if fut:
            fut.set_result({"nodeId": 42})

    mock_ws.send.side_effect = fake_send

    result = await engine.send("DOM.getDocument", {})
    assert result == {"nodeId": 42}


def test_engine_increments_id():
    engine = CDPEngine.__new__(CDPEngine)
    engine._id = 0
    engine._pending = {}
    assert engine._next_id() == 1
    assert engine._next_id() == 2
