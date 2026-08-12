from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from typing import Any

import websockets

from grip.errors.types import BrowserError, ErrorType, GripError, RecoveryAction

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
# Short and fixed, not `default_timeout`: this is a best-effort setup probe,
# not a caller-facing command, so it must not inherit a slow per-call budget
# and pin connect() behind it.
INSPECTOR_ENABLE_TIMEOUT = 5.0


class CDPEngine:
    def __init__(self, default_timeout: float = DEFAULT_TIMEOUT) -> None:
        self._ws: websockets.ClientConnection | None = None
        self._id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._listeners: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._receive_task: asyncio.Task[None] | None = None
        self._closed_reason: BrowserError | None = None
        # Per-call default for send(); a caller that wants a tighter budget for
        # one command still passes send(..., timeout=...) without touching this.
        self.default_timeout = default_timeout

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    @property
    def closed(self) -> bool:
        return self._closed_reason is not None

    @property
    def closed_reason(self) -> BrowserError | None:
        """The typed error that closed this connection, or None while open."""
        return self._closed_reason

    async def connect(self, url: str) -> None:
        self._ws = await websockets.connect(url, max_size=50 * 1024 * 1024)
        self._receive_task = asyncio.create_task(self._receive_loop())
        self.on("Inspector.targetCrashed", self._handle_target_crashed)
        # Inspector.targetCrashed is not delivered until the domain is enabled.
        # Best-effort: a target that doesn't support Inspector (rare) should not
        # prevent the connection from being usable for everything else.
        try:
            await self.send("Inspector.enable", timeout=INSPECTOR_ENABLE_TIMEOUT)
        except Exception:
            logger.debug("Inspector.enable failed; crash events will not surface", exc_info=True)

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
        timeout: float | None = None,
    ) -> Any:
        """`session_id` addresses a flattened child session (Target.setAutoAttach
        with flatten=True) sharing this same websocket — CDPEngine has always been
        one connection per CDP target, and this does not change that. It only lets
        a caller that already holds a browser- or page-level connection reach a
        session Chrome attached on top of it (a popup paused via
        waitForDebuggerOnStart, an OOPIF) without opening a second websocket.
        Response ids are unique per connection regardless of session, so the
        existing _pending lookup needs no changes to keep working.

        `timeout` overrides `self.default_timeout` for this one command; pass it
        to give a single slow-path call its own budget without lowering the
        engine-wide default for everything else."""
        if self._ws is None:
            raise RuntimeError("CDPEngine is not connected. Call connect() first.")
        if self._closed_reason is not None:
            raise GripError(self._closed_reason)
        msg_id = self._next_id()
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        message: dict[str, Any] = {"id": msg_id, "method": method, "params": params or {}}
        if session_id is not None:
            message["sessionId"] = session_id
        payload = json.dumps(message)
        await self._ws.send(payload)
        effective_timeout = timeout if timeout is not None else self.default_timeout
        try:
            return await asyncio.wait_for(fut, timeout=effective_timeout)
        except TimeoutError as e:
            self._pending.pop(msg_id, None)
            raise TimeoutError(f"CDP command {method} timed out") from e

    def on(self, event: str, callback: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def off(self, event: str, callback: Callable[[dict[str, Any]], None]) -> None:
        listeners = self._listeners.get(event, [])
        if callback in listeners:
            listeners.remove(callback)

    def _handle_target_crashed(self, params: dict[str, Any]) -> None:
        reason = params.get("reason", "unknown")
        error_code = params.get("errorCode")
        detail = f"reason={reason}"
        if error_code is not None:
            detail += f", errorCode={error_code}"
        self._fail_pending(BrowserError(
            type=ErrorType.BROWSER_CRASHED,
            message=f"Renderer process crashed ({detail})",
            confidence=1.0,
            recovery=[RecoveryAction.RETRY],
        ))

    def _as_crash_error(self, exc: BaseException) -> BrowserError:
        return BrowserError(
            type=ErrorType.BROWSER_CRASHED,
            message=f"CDP connection lost: {exc}",
            confidence=0.9,
            recovery=[RecoveryAction.RETRY],
        )

    async def _receive_loop(self) -> None:
        try:
            await self._receive_forever()
        except asyncio.CancelledError:
            # A clean disconnect() cancels this task and awaits it — that
            # cancellation must propagate so the await resolves, not get
            # relabelled as a crash.
            raise
        except BaseException as e:
            logger.debug("CDP receive loop ended: %s", e)
            self._fail_pending(self._as_crash_error(e))
        else:
            self._fail_pending(self._as_crash_error(ConnectionError("CDP receive loop ended")))

    # Without this, a dead socket leaves every in-flight future unresolved: each
    # caller waits out the full send timeout and then reports a timeout, which
    # reads as a slow page rather than a lost connection.
    def _fail_pending(self, error: BrowserError) -> None:
        self._closed_reason = error
        for future in list(self._pending.values()):
            if not future.done():
                # A fresh GripError per future: reusing one exception instance
                # across every pending call and every future send() would grow
                # one shared traceback without bound on a long-lived wedged
                # engine — the same unbounded-growth shape as the trace cap.
                future.set_exception(GripError(error))
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
