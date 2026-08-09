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
    CLICK_ELEMENT_JS,
    CLICK_REVEAL_JS,
    DISCOVER_ELEMENTS_JS,
    PAGE_TEXT_JS,
    READ_CONTENT_JS,
    SCROLL_BOTTOM_JS,
    TYPE_ELEMENT_JS,
)
from grip.compression.delta import SnapshotDelta, build_delta
from grip.compression.refs import RefRegistry
from grip.compression.summarizer import Element, PageSnapshot, Summarizer
from grip.errors.classifier import RAW_TEXT_PROBE_FLOOR, ErrorClassifier
from grip.errors.types import BrowserError, ErrorType, GripError, RecoveryAction
from grip.reader import Block, Document
from grip.resources import BLOCKED_RESOURCE_PATTERNS
from grip.security.injection import InjectionDetector
from grip.security.sanitizer import RawElement
from grip.trace import Trace, TraceEntry

# An element still has to be listed and clickable after its label is cut, so the
# label is replaced rather than the element dropped.
_ELIDED = "[elided: detected instruction-like text]"


def _same_document(current: str, requested: str) -> bool:
    """Whether two URLs address the same document for load-wait purposes.

    location.href is normalised by the browser ("https://x.test" comes back as
    "https://x.test/"), so a raw string compare would miss the common case and
    silently give up the fast path. Only the trailing slash is forgiven — query
    and fragment differences are real navigations.
    """
    if not current or not requested:
        return False
    return current.rstrip("/") == requested.rstrip("/")


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
        block_resources: bool = False,
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
        self._previous_snapshot: PageSnapshot | None = None
        self.delta: SnapshotDelta | None = None
        self._injector = InjectionDetector()
        self._classifier = ErrorClassifier()
        self._initialized = False
        self._refs = RefRegistry()
        self._current_url: str = ""
        self._status_code: int = 0
        self._content_probed_url: str = ""
        self._block_resources = block_resources

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
            self._initialized = True

    async def goto(self, url: str, timeout: float = 30.0) -> None:
        """Navigate this tab and wait for the load event.

        The timeout bounds the whole call. It previously bounded only the load
        wait, so the three CDP enables in front of it each contributed their own
        30s and goto(timeout=1) could block for a minute and a half.
        """
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
        # The cached snapshot describes the document we are leaving. Element
        # handles, refs and indices are all scoped to it, so keeping it across a
        # navigation would let an action resolve against the previous page.
        self._current_snapshot = None
        # Same reasoning for the delta baseline: a reload of the *same* URL would
        # otherwise diff against a document whose handles no longer exist, and
        # build_delta's url guard cannot see that case.
        self._previous_snapshot = None
        self.delta = None
        # Subscribe before navigating — a fast page can fire loadEventFired
        # before the navigate call returns.
        self._engine.on("Page.loadEventFired", on_load)
        self._engine.on("Network.responseReceived", on_response)
        try:
            async with asyncio.timeout(timeout):
                # Runtime goes up with the other two rather than lazily in
                # snapshot(): a page handed back by goto() has to be usable, and
                # enabling Runtime after the fact costs a round trip on the hot path.
                await asyncio.gather(
                    self._engine.send("Page.enable"),
                    self._engine.send("Network.enable"),
                    self._engine.send("Runtime.enable"),
                )
                self._initialized = True
                if self._block_resources:
                    await self._engine.send(
                        "Network.setBlockedURLs",
                        {"urls": list(BLOCKED_RESOURCE_PATTERNS)},
                    )
                # Page.loadEventFired is not replayed. If the target is already
                # sitting on the requested document, the event we just subscribed
                # to fired before we existed and will never fire again, so the
                # wait below would burn the entire timeout and then be swallowed
                # as success. Ask the page instead of assuming.
                if await self._already_at(url):
                    return
                await self._engine.send("Page.navigate", {"url": url})
                await load_event.wait()
        except TimeoutError:
            # A slow page is still a usable page: hand it back and let snapshot()
            # report whatever loaded. A dead connection is not — but that surfaces
            # as a ConnectionError from send(), which we deliberately do not catch.
            pass
        finally:
            self._engine.off("Page.loadEventFired", on_load)
            self._engine.off("Network.responseReceived", on_response)

    async def _already_at(self, url: str) -> bool:
        """True only if this target is *already* showing a finished `url`.

        Both halves matter. readyState alone is not enough: right after a
        navigation is requested the outgoing document can still report
        "complete", so gating on it alone would let goto() return before the
        requested page exists. The URL alone is not enough either — the document
        can be committed but still parsing.

        Best-effort: any failure here means "no, navigate normally", which is
        the behaviour that predates this check.
        """
        try:
            result = await self._engine.send(
                "Runtime.evaluate",
                {
                    "expression": (
                        'JSON.stringify({url: location.href,'
                        ' readyState: document.readyState})'
                    ),
                    "returnByValue": True,
                },
            )
        except Exception:  # noqa: BLE001 — a failed probe just means we navigate
            return False
        raw = result.get("result", {}).get("value")
        if not raw:
            return False
        try:
            state = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return False
        if state.get("readyState") not in ("interactive", "complete"):
            return False
        return _same_document(str(state.get("url", "")), url)

    async def close(self) -> None:
        """Close this tab and drop its CDP connection. Idempotent."""
        if self._closed:
            return
        self._closed = True
        try:
            await self._engine.disconnect()
        finally:
            # The tab outlives its websocket. Skipping this on a failed disconnect
            # leaks the target for the lifetime of the Browser.
            if self._closer and self._target_id:
                await self._closer(self._target_id)

    async def snapshot(self) -> PageSnapshot:
        await self._ensure_initialized()
        t0 = time.monotonic()
        try:
            # These three are independent CDP round trips (two Runtime.evaluate
            # calls plus a Target.getTargetInfo) that don't depend on each
            # other's results, so running them concurrently instead of one
            # after another shaves the per-call dispatch/serialize overhead off
            # all but the slowest of the three. Measured on local fixtures
            # (benchmarks/bench_grip.py): ~15-30% faster than sequential, with
            # no behaviour change since none of the three mutate page state.
            raw_elements, page_text, (title, url) = await asyncio.gather(
                self._discover_elements(), self._get_page_text(), self._get_page_info()
            )
        except Exception as e:
            err = self._classifier.classify_cdp_error(str(e))
            raise GripError(err) from e

        if self._current_url and url != self._current_url:
            self._refs.reset()
        self._current_url = url

        scan = self._injector.scan(page_text)
        safe_text = scan.safe_text
        # The guard only ever saw the CONTENT block. The title, every interactive
        # element's label and every placeholder reach the model too, and a payload
        # in any of them landed verbatim in the formatted snapshot.
        title_scan = self._injector.scan(title)
        elements_stripped = False
        for raw in raw_elements:
            if raw.text and not self._injector.scan(raw.text).is_clean:
                raw.text = _ELIDED
                elements_stripped = True
            if raw.placeholder and not self._injector.scan(raw.placeholder).is_clean:
                raw.placeholder = _ELIDED
                elements_stripped = True
            # role is the formatter's last fallback for an element with no text
            # and no placeholder (icon-only buttons), so it is printed verbatim
            # too — and it is just another page-controlled attribute.
            if raw.role and not self._injector.scan(raw.role).is_clean:
                raw.role = _ELIDED
                elements_stripped = True

        page_error = None
        _detected = self._classifier.classify_page_state(title, url, self._status_code)
        # Title/status alone missed nothing conclusive. Only now — and only if the
        # page has enough raw text to possibly exhibit the "lots of chrome, almost
        # no content" shape at all — pay for one extra CDP round trip to check it.
        # A short page (e.g. "hello") can never trip the ratio check regardless of
        # what it probes to, so skipping it here changes no outcome.
        # Once per URL, not once per snapshot. A "no usable content" verdict
        # describes the *fetch*; re-running it after an agent has been clicking
        # around answers a question nobody asked, and snapshot() is the hot path —
        # the probe is a second JS evaluation that roughly doubles its cost
        # (measured 8.8ms -> 16.1ms) for a signal that cannot change.
        needs_probe = url != self._content_probed_url
        if (
            needs_probe
            and _detected.type == ErrorType.NAVIGATION_FAILED
            and len(page_text) >= RAW_TEXT_PROBE_FLOOR
        ):
            self._content_probed_url = url
            shape = await self._probe_content_shape()
            if shape is not None:
                content_blocks, content_chars = shape
                _detected = self._classifier.classify_page_state(
                    title, url, self._status_code,
                    raw_chars=len(page_text),
                    content_chars=content_chars,
                    content_blocks=content_blocks,
                )
        if _detected.type in (
            ErrorType.ANTI_BOT_BLOCK, ErrorType.CAPTCHA_REQUIRED,
            ErrorType.RATE_LIMITED, ErrorType.AUTH_REQUIRED, ErrorType.NO_CONTENT,
        ):
            page_error = _detected

        self._version += 1
        snapshot = self._summarizer.build(
            version=self._version,
            url=url,
            title=title_scan.safe_text,
            raw_elements=raw_elements,
            page_text=safe_text,
        )
        snapshot.page_error = page_error
        # Deliberately after classify_page_state, which keys off real title strings
        # ("Just a moment...", "Access Denied"): sanitizing the title before that
        # check would let an injected title silently flip the anti-bot verdict.
        snapshot.prompt_injection = (
            scan.was_modified or title_scan.was_modified or elements_stripped
        )
        for el in snapshot.elements:
            el.ref = self._refs.assign(el.handle)
        self._refs.evict({el.handle for el in snapshot.elements})
        snapshot.tokens_estimated = self._summarizer.count_tokens(
            self._summarizer.format(snapshot)
        )
        self.delta = build_delta(self._previous_snapshot, snapshot)
        snapshot.changed_from_previous = self.delta is None or not self.delta.is_empty
        self._previous_snapshot = snapshot
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

    async def _probe_content_shape(self) -> tuple[int, int] | None:
        """One-off, best-effort check of how much content survives chrome
        stripping — used only to feed the classifier's content-shape signal.
        Never allowed to turn a working snapshot() into a raised error: any
        failure here just means the signal is skipped, not that the page failed.
        """
        try:
            result = await self._engine.send(
                "Runtime.evaluate",
                {"expression": READ_CONTENT_JS, "returnByValue": True},
            )
            raw = result.get("result", {}).get("value") or "{}"
            data = json.loads(raw) if isinstance(raw, str) else raw
            blocks = data.get("blocks", [])
            chars = sum(len(b.get("text", "")) for b in blocks)
            return len(blocks), chars
        except Exception:  # noqa: BLE001 — best-effort probe, never fail the snapshot
            return None

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
        el = self._find_element(description)
        if el is None:
            err = self._classifier.classify_semantic_miss(description)
            raise GripError(err)
        js = (
            f"({CLICK_ELEMENT_JS})"
            f"({json.dumps(el.handle)}, {json.dumps(el.tag)}, {json.dumps(el.text)})"
        )
        result = await self._engine.send(
            "Runtime.evaluate", {"expression": js, "returnByValue": True}
        )
        outcome = result.get("result", {}).get("value") or {}
        duration_ms = int((time.monotonic() - t0) * 1000)
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="click",
            input={"description": description, "handle": el.handle},
            output={"success": bool(outcome.get("ok")),
                    "reason": outcome.get("reason", "")},
            tokens_consumed=0,
            duration_ms=duration_ms,
        ))
        self._raise_for_action(outcome, description)

    async def type(self, description: str, text: str) -> None:
        self._assert_not_safe("type")
        if not self._current_snapshot:
            await self.snapshot()
        t0 = time.monotonic()
        el = self._find_input(description)
        if el is None:
            err = self._classifier.classify_semantic_miss(description)
            raise GripError(err)
        js = (
            f"({TYPE_ELEMENT_JS})"
            f"({json.dumps(el.handle)}, {json.dumps(text)}, "
            f"{json.dumps(el.tag)}, {json.dumps(el.text)})"
        )
        result = await self._engine.send(
            "Runtime.evaluate", {"expression": js, "returnByValue": True}
        )
        outcome = result.get("result", {}).get("value") or {}
        duration_ms = int((time.monotonic() - t0) * 1000)
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="type",
            input={"description": description, "text": text, "handle": el.handle},
            output={"success": bool(outcome.get("ok")),
                    "reason": outcome.get("reason", "")},
            tokens_consumed=0,
            duration_ms=duration_ms,
        ))
        self._raise_for_action(outcome, description)

    # A wrong action is worse than a failed one, so every non-ok outcome becomes a
    # typed error the runner's recovery can act on, rather than a boolean the
    # caller has no way to notice.
    def _raise_for_action(self, outcome: dict, description: str) -> None:
        if outcome.get("ok"):
            return
        reason = outcome.get("reason", "")
        if reason == "not_typable":
            raise GripError(self._classifier.classify_semantic_miss(description))
        raise GripError(
            BrowserError(
                type=ErrorType.ELEMENT_STALE,
                message=(
                    f"Element for {description!r} no longer matches the snapshot "
                    f"it was found in ({reason or 'unknown'}). Re-snapshot and retry."
                ),
                confidence=1.0,
                recovery=[RecoveryAction.RE_SNAPSHOT],
            )
        )

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

    def _find_element(self, description: str) -> Element | None:
        if not self._current_snapshot:
            return None
        # Exact ref match (e.g., "e5")
        for el in self._current_snapshot.elements:
            if el.ref == description:
                return el
        # Fuzzy text/role match
        desc_lower = description.lower()
        for el in self._current_snapshot.elements:
            if desc_lower in el.text.lower() or desc_lower in el.role.lower():
                return el
        return None

    def _find_input(self, description: str) -> Element | None:
        if not self._current_snapshot:
            return None
        # Exact ref match
        for el in self._current_snapshot.elements:
            if el.ref == description and (
                el.tag in ("input", "textarea") or el.role == "textbox"
            ):
                return el
        # Fuzzy match
        desc_lower = description.lower()
        for el in self._current_snapshot.elements:
            if (el.tag in ("input", "textarea") or el.role == "textbox") and (
                desc_lower in el.text.lower()
                or desc_lower in (el.placeholder or "").lower()
                or desc_lower in el.role.lower()
            ):
                return el
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
                handle=d.get("handle", ""),
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
