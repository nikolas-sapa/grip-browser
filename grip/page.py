from __future__ import annotations
import asyncio
import base64
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from grip.cdp.engine import CDPEngine
from grip.cdp.shadow import (
    DISCOVER_ELEMENTS_JS, CLICK_ELEMENT_JS,
    TYPE_ELEMENT_JS, PAGE_TEXT_JS, READ_CONTENT_JS,
    CLICK_REVEAL_JS, SCROLL_BOTTOM_JS,
)
from grip.compression.cache import ElementCache
from grip.compression.refs import RefRegistry
from grip.compression.diff import SnapshotDiff
from grip.compression.summarizer import PageSnapshot, Summarizer
from grip.errors.classifier import ErrorClassifier
from grip.errors.types import BrowserError, ErrorType, GripError
from grip.security.injection import InjectionDetector
from grip.reader import Block, Document
from grip.security.sanitizer import HiddenElementFilter, RawElement
from grip.trace import Trace, TraceEntry


@dataclass
class Screenshot:
    data: bytes
    tokens_estimated: int

    @property
    def b64(self) -> str:
        return base64.b64encode(self.data).decode()

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            f.write(self.data)


class Page:
    def __init__(
        self,
        engine: CDPEngine,
        trace: Trace,
        target_id: str = "",
        safe: bool = False,
        closer: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._engine = engine
        self._trace = trace
        self._target_id = target_id
        self._safe = safe
        self._closer = closer
        self._closed = False
        self._version = 0
        self._current_snapshot: PageSnapshot | None = None
        self._summarizer = Summarizer()
        self._cache = ElementCache()
        self._diff = SnapshotDiff()
        self._filter = HiddenElementFilter()
        self._injector = InjectionDetector()
        self._classifier = ErrorClassifier()
        self._initialized = False
        self._refs = RefRegistry()
        self._current_url: str = ""
        self._status_code: int = 0

    def _assert_not_safe(self, action: str) -> None:
        if self._safe:
            raise GripError(BrowserError(
                type=ErrorType.SAFE_MODE_VIOLATION,
                message=f"{action}() is not allowed in safe mode",
                confidence=1.0,
                recovery=[],
            ))

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self._engine.send("Runtime.enable")
            await self._engine.send("Page.enable")
            self._initialized = True

    async def goto(self, url: str, timeout: float = 30.0) -> None:
        """Navigate this tab and wait for the load event."""
        await self._engine.send("Page.enable")
        await self._engine.send("Network.enable")
        load_event = asyncio.Event()

        def on_load(params: dict) -> None:
            load_event.set()

        def on_response(params: dict) -> None:
            # Only the main document response carries the status that describes the
            # fetch. Sub-resources (images, XHR) fire this too and must be ignored.
            # Redirect chains fire several Document responses; the last one wins.
            if params.get("type") == "Document":
                self._status_code = params.get("response", {}).get("status", 0)

        self._status_code = 0
        # Subscribe before navigating — a fast page can fire loadEventFired
        # before the navigate call returns.
        self._engine.on("Page.loadEventFired", on_load)
        self._engine.on("Network.responseReceived", on_response)
        try:
            await self._engine.send("Page.navigate", {"url": url})
            await asyncio.wait_for(load_event.wait(), timeout=timeout)
        except TimeoutError:
            pass  # slow page: hand it back anyway, snapshot() sees whatever loaded
        finally:
            self._engine.off("Page.loadEventFired", on_load)
            self._engine.off("Network.responseReceived", on_response)

    async def close(self) -> None:
        """Close this tab and drop its CDP connection. Idempotent."""
        if self._closed:
            return
        self._closed = True
        await self._engine.disconnect()
        if self._closer and self._target_id:
            await self._closer(self._target_id)

    async def snapshot(self) -> PageSnapshot:
        await self._ensure_initialized()
        t0 = time.monotonic()
        try:
            raw_elements = await self._discover_elements()
            page_text = await self._get_page_text()
            title, url = await self._get_page_info()
        except Exception as e:
            err = self._classifier.classify_cdp_error(str(e))
            raise GripError(err) from e

        if self._current_url and url != self._current_url:
            self._refs.reset()
        self._current_url = url

        scan = self._injector.scan(page_text)
        safe_text = scan.safe_text

        page_error = None
        _detected = self._classifier.classify_page_state(title, url, self._status_code)
        if _detected.type in (
            ErrorType.ANTI_BOT_BLOCK, ErrorType.CAPTCHA_REQUIRED,
            ErrorType.RATE_LIMITED, ErrorType.AUTH_REQUIRED,
        ):
            page_error = _detected

        self._version += 1
        snapshot = self._summarizer.build(
            version=self._version,
            url=url,
            title=title,
            raw_elements=raw_elements,
            page_text=safe_text,
        )
        snapshot.page_error = page_error
        for el in snapshot.elements:
            el.ref = self._refs.assign(el.tag, el.text)
        snapshot.tokens_estimated = self._summarizer.count_tokens(
            self._summarizer.format(snapshot)
        )
        changed = self._diff.has_changed(snapshot)
        snapshot.changed_from_previous = changed
        self._diff.record(snapshot)
        self._cache.store_many(snapshot.elements)
        self._current_snapshot = snapshot

        duration_ms = int((time.monotonic() - t0) * 1000)
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="snapshot",
            input={},
            output={"version": snapshot.version, "elements": len(snapshot.elements)},
            tokens_consumed=snapshot.tokens_estimated,
            duration_ms=duration_ms,
        ))
        return snapshot

    async def read(
        self,
        max_chars: int | None = None,
        interact: bool = False,
        max_interactions: int = 3,
        interaction_timeout: float = 10.0,
    ) -> Document:
        """Read the page as prose: ordered, citable blocks with main content
        isolated and navigation chrome dropped.

        This is the counterpart to `snapshot()`. `snapshot()` answers "what can I
        click"; `read()` answers "what does this page say".

        `max_chars` truncates by dropping whole blocks from the end, so a block is
        never cut mid-sentence. Default is no limit — deciding which parts of a
        page matter is ranking, and ranking belongs to the caller.

        `interact=True` opt-in: before reading, click "show more"/"load more"/
        expander controls (or scroll for infinite-scroll pages) to surface content
        that only exists after interaction. Off by default so existing callers see
        unchanged behaviour. Block ids are assigned below, once, after interaction
        has finished — a Document is numbered once in its final state, never
        renumbered, so citations stay stable.
        """
        if interact:
            # Revealing content means clicking the page. Safe mode promises no
            # mutating actions, and this path would otherwise walk straight past
            # the guard that click()/type()/press() enforce.
            self._assert_not_safe("read(interact=True)")
        await self._ensure_initialized()
        t0 = time.monotonic()
        try:
            if interact:
                await self._interact_to_reveal(max_interactions, interaction_timeout)
            result = await self._engine.send(
                "Runtime.evaluate",
                {"expression": READ_CONTENT_JS, "returnByValue": True},
            )
        except Exception as e:
            raise GripError(self._classifier.classify_cdp_error(str(e))) from e

        raw = result.get("result", {}).get("value") or "{}"
        data = json.loads(raw) if isinstance(raw, str) else raw

        blocks: list[Block] = []
        used = 0
        for i, b in enumerate(data.get("blocks", [])):
            text = self._injector.scan(b.get("text", "")).safe_text
            if max_chars is not None and used + len(text) > max_chars:
                break
            used += len(text)
            blocks.append(
                Block(
                    id=i,
                    kind=b.get("kind", "text"),
                    text=text,
                    path=list(b.get("path", [])),
                    level=b.get("level", 0),
                )
            )

        doc = Document(
            title=data.get("title", ""), url=data.get("url", ""), blocks=blocks
        )
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="read",
            input={"max_chars": max_chars, "interact": interact},
            output={"blocks": len(blocks), "chars": used},
            tokens_consumed=self._summarizer.count_tokens(doc.text),
            duration_ms=int((time.monotonic() - t0) * 1000),
        ))
        return doc

    async def _interact_to_reveal(self, max_interactions: int, timeout: float) -> None:
        """Click/scroll to surface hidden content before the caller's read.

        Stops on whichever comes first: depth cap, a block-count plateau (an
        interaction adds under 10% new blocks), or the timeout. Infinite scroll
        gets no special casing — it just plateaus like a dead "load more" button
        once scrolling stops adding blocks.
        """
        deadline = time.monotonic() + timeout
        prev_count = await self._count_blocks()
        for _ in range(max_interactions):
            if time.monotonic() >= deadline:
                break
            await self._reveal_step()
            new_count = await self._await_block_growth(prev_count, deadline)
            plateaued = (new_count - prev_count) < max(1, prev_count * 0.10)
            prev_count = new_count
            if plateaued:
                break

    async def _await_block_growth(self, prev_count: int, deadline: float) -> int:
        """Poll after a click/scroll instead of a fixed sleep — a real "load
        more" is a fetch that can land well after any fixed delay would give up
        on, and a synchronous DOM write shouldn't cost the full poll window."""
        poll_deadline = min(deadline, time.monotonic() + 1.0)
        count = await self._count_blocks()
        while count <= prev_count and time.monotonic() < poll_deadline:
            await asyncio.sleep(0.1)
            count = await self._count_blocks()
        return count

    async def _reveal_step(self) -> bool:
        """One interaction: click a matching reveal control, or scroll to the
        bottom if none is found (covers infinite-scroll pages with no button)."""
        result = await self._engine.send(
            "Runtime.evaluate",
            {"expression": CLICK_REVEAL_JS, "returnByValue": True},
        )
        clicked = bool(result.get("result", {}).get("value", False))
        if not clicked:
            await self._engine.send(
                "Runtime.evaluate",
                {"expression": SCROLL_BOTTOM_JS, "returnByValue": True},
            )
        return clicked

    async def _count_blocks(self) -> int:
        result = await self._engine.send(
            "Runtime.evaluate",
            {"expression": READ_CONTENT_JS, "returnByValue": True},
        )
        raw = result.get("result", {}).get("value") or "{}"
        data = json.loads(raw) if isinstance(raw, str) else raw
        return len(data.get("blocks", []))

    async def click(self, description: str) -> None:
        self._assert_not_safe("click")
        if not self._current_snapshot:
            await self.snapshot()
        t0 = time.monotonic()
        index = self._find_element_index(description)
        if index is None:
            err = self._classifier.classify_semantic_miss(description)
            raise GripError(err)
        js = f"({CLICK_ELEMENT_JS})({index})"
        result = await self._engine.send(
            "Runtime.evaluate", {"expression": js, "returnByValue": True}
        )
        success = result.get("result", {}).get("value", False)
        duration_ms = int((time.monotonic() - t0) * 1000)
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="click",
            input={"description": description, "index": index},
            output={"success": success},
            tokens_consumed=0,
            duration_ms=duration_ms,
        ))

    async def type(self, description: str, text: str) -> None:
        self._assert_not_safe("type")
        if not self._current_snapshot:
            await self.snapshot()
        t0 = time.monotonic()
        index = self._find_input_index(description)
        if index is None:
            err = self._classifier.classify_semantic_miss(description)
            raise GripError(err)
        js = f"({TYPE_ELEMENT_JS})({index}, {json.dumps(text)})"
        await self._engine.send(
            "Runtime.evaluate", {"expression": js, "returnByValue": True}
        )
        duration_ms = int((time.monotonic() - t0) * 1000)
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="type",
            input={"description": description, "text": text, "index": index},
            output={"success": True},
            tokens_consumed=0,
            duration_ms=duration_ms,
        ))

    async def press(self, key: str) -> None:
        self._assert_not_safe("press")
        await self._engine.send(
            "Input.dispatchKeyEvent",
            {"type": "keyDown", "key": key},
        )
        await self._engine.send(
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "key": key},
        )

    async def extract(self, schema: dict[str, str]) -> dict[str, Any]:
        snap = await self.snapshot()
        # Returns raw page text per key — pass to an LLM for semantic parsing.
        # Use browser.run(goal, llm=...) for automatic structured extraction.
        return {key: snap.text_content for key in schema}

    async def observe(self, question: str) -> str:
        snap = await self.snapshot()
        return self._summarizer.format(snap)

    async def screenshot(self, quality: int = 75) -> Screenshot:
        """
        Capture a JPEG screenshot. quality=75 gives ~800 vision tokens vs ~3000 for PNG.

        Usage with Claude vision:
            shot = await page.screenshot()
            # shot.b64  — base64 string ready for the API
            # shot.data — raw bytes
            # shot.save("page.jpg")
        """
        t0 = time.monotonic()
        result = await self._engine.send(
            "Page.captureScreenshot",
            {"format": "jpeg", "quality": quality, "captureBeyondViewport": False},
        )
        img_bytes = base64.b64decode(result.get("data", ""))
        tokens = len(img_bytes) // 150
        duration_ms = int((time.monotonic() - t0) * 1000)
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="screenshot",
            input={"quality": quality},
            output={"bytes": len(img_bytes), "tokens_estimated": tokens},
            tokens_consumed=tokens,
            duration_ms=duration_ms,
        ))
        return Screenshot(data=img_bytes, tokens_estimated=tokens)

    def _find_element_index(self, description: str) -> int | None:
        if not self._current_snapshot:
            return None
        # Exact ref match (e.g., "e5")
        for el in self._current_snapshot.elements:
            if el.ref == description:
                return el.index
        # Fuzzy text/role match
        desc_lower = description.lower()
        for el in self._current_snapshot.elements:
            if desc_lower in el.text.lower() or desc_lower in el.role.lower():
                return el.index
        return None

    def _find_input_index(self, description: str) -> int | None:
        if not self._current_snapshot:
            return None
        # Exact ref match
        for el in self._current_snapshot.elements:
            if el.ref == description and (
                el.tag in ("input", "textarea") or el.role == "textbox"
            ):
                return el.index
        # Fuzzy match
        desc_lower = description.lower()
        for el in self._current_snapshot.elements:
            if el.tag in ("input", "textarea") or el.role == "textbox":
                if (
                    desc_lower in el.text.lower()
                    or desc_lower in (el.placeholder or "").lower()
                    or desc_lower in el.role.lower()
                ):
                    return el.index
        return None

    async def _discover_elements(self) -> list[RawElement]:
        result = await self._engine.send(
            "Runtime.evaluate",
            {"expression": DISCOVER_ELEMENTS_JS, "returnByValue": True},
        )
        raw_data = result.get("result", {}).get("value")
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)
        if not raw_data:
            return []
        return [
            RawElement(
                tag=d.get("tag", ""),
                role=d.get("role", ""),
                text=d.get("text", ""),
                placeholder=d.get("placeholder"),
                in_shadow_dom=d.get("inShadowDom", False),
                cx=d.get("cx", 0),
                cy=d.get("cy", 0),
                computed_display=d.get("computedDisplay", "block"),
                computed_visibility=d.get("computedVisibility", "visible"),
                computed_opacity=d.get("computedOpacity", "1"),
                aria_hidden=d.get("ariaHidden", False),
                width=d.get("width", 1),
                height=d.get("height", 1),
                href=d.get("href"),
            )
            for d in raw_data
        ]

    async def _get_page_text(self) -> str:
        result = await self._engine.send(
            "Runtime.evaluate",
            {"expression": PAGE_TEXT_JS, "returnByValue": True},
        )
        return result.get("result", {}).get("value", "")

    async def _get_page_info(self) -> tuple[str, str]:
        result = await self._engine.send("Target.getTargetInfo", {})
        info = result.get("targetInfo", {})
        return info.get("title", ""), info.get("url", "")
