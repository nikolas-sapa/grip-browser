from __future__ import annotations
import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

import websockets

logger = logging.getLogger(__name__)


class CDPEngine:
    def __init__(self) -> None:
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._listeners: dict[str, list[Callable]] = {}
        self._receive_task: asyncio.Task | None = None

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    async def connect(self, url: str) -> None:
        self._ws = await websockets.connect(url, max_size=50 * 1024 * 1024)
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def disconnect(self) -> None:
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send(self, method: str, params: dict[str, Any] | None = None) -> Any:
        msg_id = self._next_id()
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut
        payload = json.dumps({"id": msg_id, "method": method, "params": params or {}})
        await self._ws.send(payload)
        try:
            return await asyncio.wait_for(fut, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise TimeoutError(f"CDP command {method} timed out")

    def on(self, event: str, callback: Callable) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def off(self, event: str, callback: Callable) -> None:
        listeners = self._listeners.get(event, [])
        if callback in listeners:
            listeners.remove(callback)

    async def _receive_loop(self) -> None:
        try:
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
        except Exception:
            logger.debug("CDP receive loop ended")
