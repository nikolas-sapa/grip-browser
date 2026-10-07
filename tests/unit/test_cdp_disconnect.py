import asyncio
import json

import pytest

from grip.cdp.engine import CDPEngine


class PendingSocket:
    def __init__(self, hold_close=False):
        self.sent = []
        self.three_sent = asyncio.Event()
        self.close_started = asyncio.Event()
        self.release_close = asyncio.Event()
        if not hold_close:
            self.release_close.set()

    async def send(self, payload):
        self.sent.append(json.loads(payload))
        if len(self.sent) == 3:
            self.three_sent.set()

    async def close(self):
        self.close_started.set()
        await self.release_close.wait()


@pytest.mark.asyncio
async def test_explicit_disconnect_fails_all_inflight_sessions_immediately():
    engine = CDPEngine(default_timeout=30)
    socket = PendingSocket()
    engine._ws = socket
    engine._receive_task = asyncio.create_task(asyncio.Event().wait())
    calls = [asyncio.create_task(engine.send("Runtime.evaluate", session_id=session))
             for session in (None, "child-a", "child-b")]
    try:
        await asyncio.wait_for(socket.three_sent.wait(), 1)
        await engine.disconnect()
        async with asyncio.timeout(0.25):
            for call in calls:
                with pytest.raises(RuntimeError, match="disconnected"):
                    await call
        assert engine._pending == {}
        assert len(socket.sent) == 3
    finally:
        for call in calls:
            call.cancel()
        await asyncio.gather(*calls, return_exceptions=True)


@pytest.mark.asyncio
async def test_disconnect_rejects_new_commands_while_socket_close_is_pending():
    engine = CDPEngine()
    socket = PendingSocket(hold_close=True)
    engine._ws = socket
    close = asyncio.create_task(engine.disconnect())
    try:
        await asyncio.wait_for(socket.close_started.wait(), 1)
        with pytest.raises(RuntimeError, match="disconnect"):
            await engine.send("Runtime.evaluate", timeout=0.01)
        assert socket.sent == []
    finally:
        socket.release_close.set()
        await close


@pytest.mark.asyncio
async def test_disconnect_then_cancel_blocked_send_retrieves_future_exception():
    engine = CDPEngine()
    socket = PendingSocket()
    send_started = asyncio.Event()
    release_send = asyncio.Event()

    async def blocked_send(payload):
        send_started.set()
        await release_send.wait()

    socket.send = blocked_send
    engine._ws = socket
    call = asyncio.create_task(engine.send("Runtime.evaluate"))
    await asyncio.wait_for(send_started.wait(), 1)
    future = next(iter(engine._pending.values()))
    try:
        await engine.disconnect()
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        assert engine._pending == {}
        assert not future._log_traceback
    finally:
        call.cancel()
        await asyncio.gather(call, return_exceptions=True)
        if future.done() and not future.cancelled():
            future.exception()
