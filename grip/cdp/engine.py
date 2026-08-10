from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from typing import Any

import websockets

logger = logging.getLogger(__name__)


class CDPEngine:
    def __init__(self) -> None:
        self._ws: websockets.ClientConnection | None = None
        self._id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._listeners: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._receive_task: asyncio.Task[None] | None = None
        self._closed_reason: BaseException | None = None

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    async def connect(self, url: str) -> None:
        self._ws = await websockets.connect(url, max_size=50 * 1024 * 1024)
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def disconnect(self) -> None:
        if self._receive_task:
            self._receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._receive_task
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> Any:
        """`session_id` addresses a flattened child session (Target.setAutoAttach
        with flatten=True) sharing this same websocket — CDPEngine has always been
        one connection per CDP target, and this does not change that. It only lets
        a caller that already holds a browser- or page-level connection reach a
        session Chrome attached on top of it (a popup paused via
        waitForDebuggerOnStart, an OOPIF) without opening a second websocket.
        Response ids are unique per connection regardless of session, so the
        existing _pending lookup needs no changes to keep working."""
        if self._ws is None:
            raise RuntimeError("CDPEngine is not connected. Call connect() first.")
        if self._closed_reason is not None:
            raise ConnectionError(
                f"CDP connection is closed: {self._closed_reason}"
            ) from self._closed_reason
        msg_id = self._next_id()
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        message: dict[str, Any] = {"id": msg_id, "method": method, "params": params or {}}
        if session_id is not None:
            message["sessionId"] = session_id
        payload = json.dumps(message)
        await self._ws.send(payload)
        try:
            return await asyncio.wait_for(fut, timeout=30.0)
        except TimeoutError as e:
            self._pending.pop(msg_id, None)
            raise TimeoutError(f"CDP command {method} timed out") from e

    def on(self, event: str, callback: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def off(self, event: str, callback: Callable[[dict[str, Any]], None]) -> None:
        listeners = self._listeners.get(event, [])
        if callback in listeners:
            listeners.remove(callback)

    async def _receive_loop(self) -> None:
        try:
            await self._receive_forever()
        except BaseException as e:
            logger.debug("CDP receive loop ended: %s", e)
            self._fail_pending(e)
            raise
        else:
            self._fail_pending(ConnectionError("CDP receive loop ended"))

    # Without this, a dead socket leaves every in-flight future unresolved: each
    # caller waits out the full send timeout and then reports a timeout, which
    # reads as a slow page rather than a lost connection.
    def _fail_pending(self, exc: BaseException) -> None:
        self._closed_reason = exc
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()

    async def _receive_forever(self) -> None:
        assert self._ws is not None  # set by connect() just before this task is created
        async for raw in self._ws:
            msg = json.loads(raw)
            if "id" in msg:
                fut = self._pending.pop(msg["id"], None)
                if fut and not fut.done():
                    if "error" in msg:
                        fut.set_exception(RuntimeError(msg["error"]["message"]))
                    else:
                        fut.set_result(msg.get("result", {}))
            elif "method" in msg:
                for cb in self._listeners.get(msg["method"], []):
                    try:
                        cb(msg.get("params", {}))
                    except Exception:
                        logger.exception("CDP listener error for %s", msg["method"])
