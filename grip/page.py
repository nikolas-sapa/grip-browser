from __future__ import annotations
import base64
import json
import time
from dataclasses import dataclass
from typing import Any

from grip.cdp.engine import CDPEngine
from grip.cdp.shadow import (
    DISCOVER_ELEMENTS_JS, CLICK_ELEMENT_JS,
    TYPE_ELEMENT_JS, PAGE_TEXT_JS,
)
from grip.compression.cache import ElementCache
from grip.compression.refs import RefRegistry
from grip.compression.diff import SnapshotDiff
from grip.compression.summarizer import PageSnapshot, Summarizer
from grip.errors.classifier import ErrorClassifier
from grip.errors.types import BrowserError, ErrorType, GripError
from grip.security.injection import InjectionDetector
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
    def __init__(self, engine: CDPEngine, trace: Trace, target_id: str = "", safe: bool = False) -> None:
        self._engine = engine
        self._trace = trace
        self._target_id = target_id
        self._safe = safe
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
        _detected = self._classifier.classify_page_state(title, url, 0)
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
