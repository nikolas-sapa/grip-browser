import asyncio
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock
from grip.cdp.engine import CDPEngine
from grip.errors.types import ErrorType, GripError


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
    with pytest.raises(GripError) as exc_info:
        await engine.send("Runtime.evaluate", {"expression": "1"})
    assert exc_info.value.error.type == ErrorType.BROWSER_CRASHED
    assert time.monotonic() - start < 1.0, "send waited on the full 30s timeout"

class _NeverRespondsSocket:
    """Accepts sends but never produces a matching response — used to prove a
    per-call timeout expires on its own schedule, not the engine's default."""

    async def send(self, data):
        pass


@pytest.mark.asyncio
async def test_send_timeout_override_expires_before_default():
    engine = CDPEngine(default_timeout=30.0)
    engine._ws = _NeverRespondsSocket()

    start = time.monotonic()
    with pytest.raises(TimeoutError):
        await engine.send("Runtime.evaluate", {"expression": "1"}, timeout=0.05)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, "per-call timeout did not override the 30s default"


@pytest.mark.asyncio
async def test_send_uses_engine_default_timeout_when_no_override_given():
    """Proves send() actually reads self.default_timeout, not just that a
    per-call override works — a no-op default would pass the override test
    above but let this one hang for the full module DEFAULT_TIMEOUT."""
    engine = CDPEngine(default_timeout=0.05)
    engine._ws = _NeverRespondsSocket()

    start = time.monotonic()
    with pytest.raises(TimeoutError):
        await engine.send("Runtime.evaluate", {"expression": "1"})
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, "engine default_timeout was not honored"


@pytest.mark.asyncio
async def test_engine_closed_reflects_connection_state():
    engine = CDPEngine()
    engine._ws = _FakeSocket(die_after=0)
    assert engine.closed is False
    assert engine.closed_reason is None

    engine._receive_task = asyncio.create_task(engine._receive_loop())
    with pytest.raises(GripError):
        await engine.send("Runtime.evaluate", {"expression": "1"})

    assert engine.closed is True
    assert engine.closed_reason is not None
    assert engine.closed_reason.type == ErrorType.BROWSER_CRASHED


@pytest.mark.asyncio
async def test_target_crashed_event_fails_pending_with_typed_error():
    engine = CDPEngine()
    engine._ws = MagicMock()

    fut = asyncio.get_running_loop().create_future()
    engine._pending[1] = fut

    engine._handle_target_crashed({"reason": "oom", "errorCode": 5})

    assert engine.closed is True
    assert fut.done()
    with pytest.raises(GripError) as exc_info:
        fut.result()
    assert exc_info.value.error.type == ErrorType.BROWSER_CRASHED
    assert "oom" in exc_info.value.error.message


@pytest.mark.asyncio
async def test_receive_loop_does_not_reraise_into_the_void():
    """A dead task nobody awaits must not raise — that's the 'exception never
    retrieved' noise this fix removes. Awaiting it here must return cleanly."""
    engine = CDPEngine()
    engine._ws = _FakeSocket(die_after=0)
    task = asyncio.create_task(engine._receive_loop())
    await task  # would raise ConnectionResetError before the fix
    assert engine.closed is True
