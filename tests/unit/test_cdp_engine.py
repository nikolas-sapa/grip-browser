import asyncio
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from grip.cdp.engine import CDPEngine


class _FakeSocket:
    """Closes on first recv, so the receive loop exits with sends still pending."""

    def __init__(self, die_after: int = 0) -> None:
        self._die_after = die_after
        self._sent = 0

    async def send(self, data):
        self._sent += 1

    async def recv(self):
        raise ConnectionResetError("peer went away")

    def __aiter__(self):
        return self

    async def __anext__(self):
        # The engine iterates the socket rather than calling recv(), so the death
        # has to surface here for the test to exercise the real path.
        return await self.recv()

    async def close(self):
        pass


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
    engine = CDPEngine()
    engine._ws = mock_ws

    async def fake_send(msg_str):
        msg = json.loads(msg_str)
        fut = engine._pending.get(msg["id"])
        if fut:
            fut.set_result({"nodeId": 42})

    mock_ws.send.side_effect = fake_send

    result = await engine.send("DOM.getDocument", {})
    assert result == {"nodeId": 42}


def test_engine_increments_id():
    engine = CDPEngine()
    assert engine._next_id() == 1
    assert engine._next_id() == 2


@pytest.mark.asyncio
async def test_dead_receive_loop_fails_pending_sends_fast():
    engine = CDPEngine()
    engine._ws = _FakeSocket(die_after=0)
    engine._receive_task = asyncio.create_task(engine._receive_loop())
    await asyncio.sleep(0)

    start = time.monotonic()
    with pytest.raises((ConnectionError, RuntimeError)):
        await engine.send("Runtime.evaluate", {"expression": "1"})
    assert time.monotonic() - start < 1.0, "send waited on the full 30s timeout"
