from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import math
import random
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
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
from grip.challenge import (
    POINT_PROBE_JS,
    SLIDER_PROBE_JS,
    TOKEN_PROBE_JS,
    ChallengeResult,
    ChallengeStage,
    detect_challenge_from_html,
    frame_urls,
    is_solvable,
    needs_vision,
)
from grip.compression.delta import SnapshotDelta, build_delta, format_delta, is_worth_sending
from grip.compression.refs import RefRegistry
from grip.compression.summarizer import Element, PageSnapshot, Summarizer
from grip.errors.classifier import RAW_TEXT_PROBE_FLOOR, ErrorClassifier
from grip.errors.types import BrowserError, ErrorType, GripError, RecoveryAction
from grip.input import RESOLVE_POINT_JS, bezier_path, move_delay, press_dwell
from grip.reader import Block, Document
from grip.resources import BLOCKED_RESOURCE_PATTERNS
from grip.security.injection import InjectionDetector
from grip.security.policy import NavigationPolicy, enforce as enforce_navigation
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


def render_payload(
    snap: PageSnapshot | None,
    delta: SnapshotDelta | None,
    last_sent_version: int,
    summarizer: Summarizer,
) -> tuple[str, int]:
    """Free function behind `Page.payload()`, kept separate so callers that
    don't hold a real Page (tests, and formerly two independent copies of this
    exact branch in grip.mcp.server and Runner) can exercise the decision
    directly against a snapshot/delta pair instead of a full Page double.

    Returns (text, new_last_sent_version).
    """
    if snap is None:
        # Every path here snapshots first, so this is a bug in the caller, not a
        # page state. Raising is what a server can afford: it turns into one
        # error result the client can act on and the process keeps serving,
        # whereas formatting nothing would answer with an empty page as if it
        # were the truth.
        raise RuntimeError(
            "payload() called before any snapshot; the page has no state to send"
        )
    rendered_snapshot = summarizer.format(snap)
    # A delta is only readable against a baseline the client actually received.
    # click()/type() snapshot implicitly when the ref cache is cold (which is the
    # state goto() leaves behind), advancing the page's baseline without emitting
    # anything. "A delta exists" is therefore not the same question as "the
    # client can apply it", and getting that wrong describes refs it has never
    # seen.
    if delta is not None and delta.previous_version == last_sent_version:
        rendered_delta = format_delta(delta)
        # Falling through to the snapshot has to move the baseline to the
        # snapshot's version, not the delta's: the client is being shown the
        # full page, and the next delta must be written against that.
        if is_worth_sending(rendered_delta, rendered_snapshot):
            return rendered_delta, delta.version
    return rendered_snapshot, snap.version


@dataclass
class Screenshot:
    data: bytes
    tokens_estimated: int

    @property
    def b64(self) -> str:
        return base64.b64encode(self.data).decode()

    def save(self, path: str) -> None:
        Path(path).write_bytes(self.data)


class Page:
    def __init__(
        self,
        engine: CDPEngine,
        trace: Trace,
        target_id: str = "",
        safe: bool = False,
        closer: Callable[[str], Awaitable[None]] | None = None,
        block_resources: bool = False,
        policy: NavigationPolicy | None = None,
    ) -> None:
        self._engine = engine
        self._trace = trace
        self._target_id = target_id
        self._safe = safe
        self._closer = closer
        # Fail-closed default: a Page built without going through Browser.open()
        # (a direct construction, or a future call site that forgets to thread
        # the Browser's policy through) still refuses private/file/metadata
        # targets rather than silently allowing everything.
        self._policy = policy if policy is not None else NavigationPolicy()
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
        # Where the synthetic pointer currently sits, so a human path starts from
        # the last position instead of teleporting to the target every time.
        self._pointer_x = 0
        self._pointer_y = 0
        # Fetch-domain interception (see _ensure_fetch_interception): enabled
        # once, for the page's lifetime, not re-armed per goto(). Set by
        # goto() while it is in flight so the persistent Fetch handler below
        # can report a refused top-level document back to the call that is
        # actually waiting on it.
        self._fetch_enabled = False
        self._doc_refusal_hook: Callable[[str], None] | None = None
        # Popup blocking (see _ensure_popup_blocking): armed once per page
        # lifetime, from goto()'s gather — same "once, not per-navigation"
        # reasoning as _fetch_enabled above.
        self._popup_block_armed = False
        # Fire-and-forget tasks spawned from synchronous CDP event handlers
        # (_on_fetch_paused, _on_target_attached) below, which cannot await
        # directly. asyncio only holds a weak reference to a task started via
        # ensure_future/create_task, so without this the task can be
        # garbage-collected mid-flight — silently dropping a
        # Fetch.continueRequest/failRequest or a Target.closeTarget/
        # runIfWaitingForDebugger call and hanging the request/target it was
        # meant to resolve.
        self._bg_tasks: set[asyncio.Task[None]] = set()

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
        # Covers pages reached without goto() (remote CDP attach, an adopted
        # target) — goto() is the common path but not the only entry point,
        # and post-load page JS is exactly what Finding 1 is about.
        await self._ensure_fetch_interception()

    async def _ensure_fetch_interception(self) -> None:
        """Pause every request the browser is about to send, so a refused one
        never leaves — as opposed to the old Network.requestWillBeSent
        observer, which only ever saw a request Chrome had already issued
        (DNS resolved, connection opened) and could at best race a
        Page.stopLoading against it after the fact.

        Enabled once for the page's lifetime, not per-navigation: a listener
        that only lived inside goto() protected the initial URL and its
        redirect chain but nothing page JS did after load fired — fetch()/XHR,
        window.location, a delayed iframe. Fetch.enable applies to
        sub-resources and later navigations on this target too, so one
        registration covers all of it.

        window.open() is NOT covered here — it creates a brand-new CDP target
        with its own independent Fetch-domain state, and Fetch.enable on this
        target does nothing for it. See _ensure_popup_blocking() for that gap.

        Gated on the policy actually being able to refuse anything: a
        Fetch-domain round trip per request is a real cost, and an
        allow_private=True caller has already opted out of restriction, so
        there is nothing for interception to buy them.
        """
        if self._fetch_enabled or self._policy.allow_private:
            return
        self._fetch_enabled = True
        self._engine.on("Fetch.requestPaused", self._on_fetch_paused)
        await self._engine.send(
            "Fetch.enable",
            {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]},
        )

    def _spawn_bg(self, coro: Coroutine[Any, Any, None]) -> None:
        """Schedule `coro` and keep a strong reference until it finishes.

        Used from synchronous CDP event handlers, which cannot await. A bare
        asyncio.ensure_future() is only weakly referenced by the loop, so the
        task can be garbage-collected before it runs — see the _bg_tasks
        comment in __init__.
        """
        task = asyncio.ensure_future(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    def _on_fetch_paused(self, params: dict[str, Any]) -> None:
        """Fetch.requestPaused handler: the request is already suspended in
        the browser, so a refusal here is preventive, not a race. Runs
        synchronously (CDPEngine dispatches listeners inline) and hands the
        actual continue/fail CDP call off to the event loop — the browser is
        happy to wait on a paused request across a task switch."""
        request_id = params.get("requestId", "")
        url = params.get("request", {}).get("url", "")
        reason = self._policy.check(url)
        if reason is None:
            self._spawn_bg(self._continue_fetch(request_id))
            return
        # Sub-resources are blocked silently — a page legitimately pulls in
        # many third-party resources, and a refused image or ad script is not
        # something the caller needs to fail loudly over. The top-level
        # document is different: goto() should not return as if a blocked
        # page had loaded, so a waiting goto() is told directly rather than
        # relying on it to notice a blank/errored page on its own.
        #
        # "Document" alone is not enough to mean "the top-level document" — a
        # blocked IFRAME navigation also pauses with resourceType "Document",
        # and treating that as the main navigation would raise
        # NAVIGATION_REFUSED out of goto() for what was only a sub-frame
        # block. The main frame's id equals this target's id, so comparing
        # against it tells the two apart. self._target_id can be empty for a
        # Page built without going through Browser.open() (see __init__); in
        # that case there is no id to compare against, so this falls back to
        # the old behaviour rather than silently never firing the hook.
        is_main_frame = not self._target_id or params.get("frameId") == self._target_id
        if (
            params.get("resourceType") == "Document"
            and self._doc_refusal_hook is not None
            and is_main_frame
        ):
            self._doc_refusal_hook(url)
        self._spawn_bg(self._fail_fetch(request_id))

    async def _continue_fetch(self, request_id: str) -> None:
        # Best-effort: the target can vanish (navigation superseded it, tab
        # closed) between the pause and this call, which is not a bug here.
        with contextlib.suppress(Exception):
            await self._engine.send("Fetch.continueRequest", {"requestId": request_id})

    async def _fail_fetch(self, request_id: str) -> None:
        with contextlib.suppress(Exception):
            await self._engine.send(
                "Fetch.failRequest",
                {"requestId": request_id, "errorReason": "AccessDenied"},
            )

    async def _ensure_popup_blocking(self) -> None:
        """window.open() (and an <a target="_blank"> click) creates a brand-new
        CDP target with its own Fetch-domain state; Fetch.enable above never
        touches it, so page JS could otherwise pop
        `window.open('http://169.254.169.254/latest/meta-data/')` into a new
        tab with zero policy enforcement.

        Chosen fix: block the popup outright rather than arm interception on
        it. Arming interception on a second target properly would mean
        session-scoped command routing plus demuxing Fetch.requestPaused by
        session — real work CDPEngine has never had to do, since every Page
        has owned exactly one target/one websocket. Page never follows a
        popup anyway (nothing here reads `Target.createTarget`'s result for
        anything but the tab this Page already is), so a popup that never
        opens costs nothing this class provides today.

        Target.setAutoAttach, sent on this target's own connection, scopes
        the attach to targets *this* target opens — popups and OOPIF
        (out-of-process) iframes both arrive this way. waitForDebuggerOnStart
        is what makes the block airtight: Chrome pauses the new target before
        it runs any JS or issues its initial navigation, and it stays paused
        until something calls Runtime.runIfWaitingForDebugger — closing it
        instead means the popup never gets far enough to request anything.

        Gated the same as Fetch interception: nothing to enforce once the
        caller has opted into allow_private.
        """
        if self._popup_block_armed or self._policy.allow_private:
            return
        self._popup_block_armed = True
        self._engine.on("Target.attachedToTarget", self._on_target_attached)
        await self._engine.send(
            "Target.setAutoAttach",
            {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True},
        )

    def _on_target_attached(self, params: dict[str, Any]) -> None:
        """Every child target this page's target opens arrives here, paused.

        Only `type == "page"` is a popup — a real new tab/window from
        window.open() or target=_blank. Everything else auto-attach can hand
        us (an OOPIF, a worker) is a normal part of rendering this page and
        has to be resumed immediately or it hangs forever; it is not
        something Page ever intended to block.
        """
        target_info = params.get("targetInfo", {})
        session_id = params.get("sessionId", "")
        if target_info.get("type") == "page":
            target_id = target_info.get("targetId", "")
            if target_id:
                self._spawn_bg(self._close_popup_target(target_id))
            return
        self._spawn_bg(self._resume_attached_target(session_id))

    async def _close_popup_target(self, target_id: str) -> None:
        # Deliberately never Runtime.runIfWaitingForDebugger first — resuming
        # it, even briefly, is exactly the race this exists to avoid.
        with contextlib.suppress(Exception):
            await self._engine.send("Target.closeTarget", {"targetId": target_id})

    async def _resume_attached_target(self, session_id: str) -> None:
        with contextlib.suppress(Exception):
            await self._engine.send(
                "Runtime.runIfWaitingForDebugger", {}, session_id=session_id
            )

    async def goto(self, url: str, timeout: float = 30.0) -> None:
        """Navigate this tab and wait for the load event.

        The timeout bounds the whole call. It previously bounded only the load
        wait, so the three CDP enables in front of it each contributed their own
        30s and goto(timeout=1) could block for a minute and a half.
        """
        load_event = asyncio.Event()
        # Set once the top-level document is refused by the Fetch-domain
        # handler below — the initial URL (checked synchronously two lines
        # down) or any redirect leg, since each leg pauses again before it is
        # sent. Preventive: by the time this fires, Fetch.failRequest has
        # already kept the request from ever reaching the target host.
        refused_url: str | None = None

        def on_load(_params: dict[str, Any]) -> None:
            load_event.set()

        def on_response(params: dict[str, Any]) -> None:
            # Only the main document response carries the status that describes the
            # fetch. Sub-resources (images, XHR) fire this too and must be ignored.
            # Redirect chains fire several Document responses; the last one wins.
            if params.get("type") == "Document":
                self._status_code = params.get("response", {}).get("status", 0)

        def on_document_refused(request_url: str) -> None:
            nonlocal refused_url
            if refused_url is None:
                refused_url = request_url
                load_event.set()

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
        enforce_navigation(self._policy, url)
        # Subscribe before navigating — a fast page can fire loadEventFired
        # before the navigate call returns.
        self._engine.on("Page.loadEventFired", on_load)
        self._engine.on("Network.responseReceived", on_response)
        # Only this goto() cares about a refused top-level document; the
        # Fetch handler itself lives for the page's whole lifetime.
        self._doc_refusal_hook = on_document_refused
        try:
            async with asyncio.timeout(timeout):
                # Runtime goes up with the other two rather than lazily in
                # snapshot(): a page handed back by goto() has to be usable, and
                # enabling Runtime after the fact costs a round trip on the hot path.
                await asyncio.gather(
                    self._engine.send("Page.enable"),
                    self._engine.send("Network.enable"),
                    self._engine.send("Runtime.enable"),
                    self._ensure_fetch_interception(),
                    self._ensure_popup_blocking(),
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
            self._doc_refusal_hook = None
        if refused_url is not None:
            enforce_navigation(self._policy, refused_url)

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
        except Exception:
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

    def payload(self, last_sent_version: int) -> tuple[str, int]:
        """Render the current snapshot as a delta against `last_sent_version`, or
        as a full snapshot if there is no delta, the delta isn't readable against
        that baseline, or the delta doesn't actually save anything.

        The single home for a decision every caller needs: grip.mcp.server and
        Runner both send "what changed since the client last saw the page", and
        used to carry two copies of this exact algorithm (same branches, same
        comments) reaching into `_current_snapshot`/`delta` independently. One
        drifting out of sync with the other was only a matter of time.

        Returns (text, new_last_sent_version) — the caller owns tracking what its
        client actually holds; the page doesn't know how many clients are asking.
        """
        return render_payload(
            self._current_snapshot, self.delta, last_sent_version, self._summarizer
        )

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
        except Exception:
            return None

    async def _count_blocks(self) -> int:
        result = await self._engine.send(
            "Runtime.evaluate",
            {"expression": READ_CONTENT_JS, "returnByValue": True},
        )
        raw = result.get("result", {}).get("value") or "{}"
        data = json.loads(raw) if isinstance(raw, str) else raw
        return len(data.get("blocks", []))

    async def click(self, description: str, *, human: bool = False) -> None:
        self._assert_not_safe("click")
        if not self._current_snapshot:
            await self.snapshot()
        t0 = time.monotonic()
        el = self._find_element(description)
        if el is None:
            err = self._classifier.classify_semantic_miss(description)
            raise GripError(err)
        if human:
            # Default stays the JS path: it is faster and works headless.
            # human=True is for challenge flows, where the approach to the target
            # is itself scored. It re-resolves the handle first rather than
            # trusting the snapshot's cx/cy, so a stale element still raises
            # instead of putting a real click on whatever now occupies that spot.
            probe = await self._eval(
                f"({RESOLVE_POINT_JS})"
                f"({json.dumps(el.handle)}, {json.dumps(el.tag)}, {json.dumps(el.text)})"
            )
            outcome = probe or {}
            self._trace.add(TraceEntry(
                timestamp=time.time(),
                action="click",
                input={"description": description, "handle": el.handle, "human": True},
                output={"success": bool(outcome.get("ok")),
                        "reason": outcome.get("reason", "")},
                tokens_consumed=0,
                duration_ms=int((time.monotonic() - t0) * 1000),
            ))
            self._raise_for_action(outcome, description)
            await self.click_at(int(outcome["x"]), int(outcome["y"]), human=True)
            return
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
    def _raise_for_action(self, outcome: dict[str, Any], description: str) -> None:
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

    async def click_at(
        self, x: int, y: int, *, human: bool = True, rng: random.Random | None = None
    ) -> None:
        """Click real viewport coordinates with a trusted pointer event.

        click() dispatches an untrusted JS event with no pointer motion at all,
        which is fine for ordinary pages and useless for challenge widgets that
        score the approach to the target. This path moves along a curved, eased
        Bezier first, then presses with a randomized dwell.
        """
        self._assert_not_safe("click_at")
        t0 = time.monotonic()
        moves = 0
        if human:
            moves = await self._move_pointer((self._pointer_x, self._pointer_y), (x, y), rng)
        await self._mouse(
            "mousePressed", x, y, button="left", click_count=1
        )
        await asyncio.sleep(press_dwell(rng))
        await self._mouse(
            "mouseReleased", x, y, button="left", click_count=1
        )
        self._pointer_x, self._pointer_y = x, y
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="click_at",
            input={"x": x, "y": y, "human": human},
            output={"moves": moves},
            tokens_consumed=0,
            duration_ms=int((time.monotonic() - t0) * 1000),
        ))

    async def drag(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        *,
        human: bool = True,
        rng: random.Random | None = None,
    ) -> None:
        """Press at start, travel to end with the button held, release.

        The slider primitive. The button stays down for every intermediate move:
        a released mid-path pointer is not a drag and sliders reject it.
        """
        self._assert_not_safe("drag")
        t0 = time.monotonic()
        # Jitter shaped like a hand, not a nonce.
        r = rng or random.Random()  # noqa: S311
        sx, sy = start
        ex, ey = end
        await self._mouse("mousePressed", sx, sy, button="left", click_count=1)

        path = bezier_path(start, end, rng=rng) if human else [end]
        # Slight overshoot-and-correct: a hand rarely lands a slider handle dead
        # on the stop at the first attempt.
        if human and (ex, ey) != (sx, sy):
            over = r.randint(3, 9)
            dx, dy = ex - sx, ey - sy
            norm = math.hypot(dx, dy) or 1.0
            path.append((int(ex + dx / norm * over), int(ey + dy / norm * over)))
            path.append((ex, ey))

        for px, py in path:
            await self._mouse("mouseMoved", px, py, button="left")
            if human:
                await asyncio.sleep(move_delay(r))
        await self._mouse("mouseReleased", ex, ey, button="left", click_count=1)
        self._pointer_x, self._pointer_y = ex, ey
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="drag",
            input={"start": list(start), "end": list(end), "human": human},
            output={"moves": len(path)},
            tokens_consumed=0,
            duration_ms=int((time.monotonic() - t0) * 1000),
        ))

    async def _move_pointer(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        rng: random.Random | None = None,
    ) -> int:
        r = rng or random.Random()  # noqa: S311
        path = bezier_path(start, end, rng=rng)
        for px, py in path:
            await self._mouse("mouseMoved", px, py)
            await asyncio.sleep(move_delay(r))
        return len(path)

    async def _mouse(
        self,
        event_type: str,
        x: int,
        y: int,
        *,
        button: str = "none",
        click_count: int = 0,
    ) -> None:
        params: dict[str, Any] = {"type": event_type, "x": x, "y": y, "button": button}
        if click_count:
            params["clickCount"] = click_count
        await self._engine.send("Input.dispatchMouseEvent", params)

    async def detect_challenge(self) -> ChallengeStage:
        """Classify any bot challenge on the page. Read-only, no network calls."""
        # A Page reached without goto() (remote CDP attach, an adopted target)
        # has no Runtime domain enabled, and every probe below is an evaluate.
        await self._ensure_initialized()
        html = await self._page_html()
        tree = await self._engine.send("Page.getFrameTree")
        return detect_challenge_from_html(html, frame_urls(tree or {}))

    async def solve_challenge(self, timeout: float = 30.0) -> ChallengeResult:
        """Attempt the challenge in-process and report a verified outcome.

        status is one of: none, solved, needs_vision, unsupported, timeout.
        "solved" is only returned once a response token is present or the widget
        has left the DOM. Nothing here calls a third-party solving service.
        """
        self._assert_not_safe("solve_challenge")
        t0 = time.monotonic()
        stage = await self.detect_challenge()

        if stage is ChallengeStage.NONE:
            result = ChallengeResult(status="none", stage=stage)
        elif needs_vision(stage):
            shot = await self.screenshot()
            result = ChallengeResult(
                status="needs_vision",
                stage=stage,
                detail=(
                    f"{stage.value} challenge needs a vision model to answer. "
                    "Pass result.screenshot to your model, then act with "
                    "page.click_at(x, y, human=True)."
                ),
                screenshot=shot,
            )
        elif not is_solvable(stage):
            result = ChallengeResult(
                status="unsupported",
                stage=stage,
                detail=(
                    f"{stage.value} challenge has no in-process solve path. "
                    "It is scored server-side or grip could not identify the widget."
                ),
            )
        elif stage is ChallengeStage.SLIDER:
            result = await self._solve_slider(stage, timeout)
        else:
            result = await self._solve_click_widget(stage, timeout)

        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="solve_challenge",
            input={"timeout": timeout},
            output={"stage": stage.value, "status": result.status},
            tokens_consumed=0,
            duration_ms=int((time.monotonic() - t0) * 1000),
        ))
        return result

    async def _solve_click_widget(
        self, stage: ChallengeStage, timeout: float
    ) -> ChallengeResult:
        deadline = time.monotonic() + timeout
        point = await self._eval(POINT_PROBE_JS)
        if not isinstance(point, dict):
            return ChallengeResult(
                status="unsupported",
                stage=stage,
                detail="Widget frame has no measurable box; nothing to click.",
            )
        await self.click_at(int(point["x"]), int(point["y"]), human=True)
        return await self._await_verification(stage, deadline)

    async def _solve_slider(
        self, stage: ChallengeStage, timeout: float
    ) -> ChallengeResult:
        deadline = time.monotonic() + timeout
        geom = await self._eval(SLIDER_PROBE_JS)
        if not isinstance(geom, dict):
            return ChallengeResult(
                status="unsupported",
                stage=stage,
                detail="Could not locate the slider handle and its track.",
            )
        await self.drag(
            (int(geom["x"]), int(geom["y"])),
            (int(geom["endX"]), int(geom["y"])),
            human=True,
        )
        return await self._await_verification(stage, deadline)

    async def _await_verification(
        self, stage: ChallengeStage, deadline: float
    ) -> ChallengeResult:
        """Poll until the challenge is provably gone, or give up honestly.

        The click having been dispatched proves nothing — providers score the
        interaction and may silently refuse. Only a token or a vanished widget
        is evidence, and without either this returns "timeout".
        """
        while True:
            token = await self._eval(TOKEN_PROBE_JS)
            if isinstance(token, str) and token:
                return ChallengeResult(
                    status="solved", stage=stage, detail="Response token present."
                )
            if await self.detect_challenge() is ChallengeStage.NONE:
                return ChallengeResult(
                    status="solved", stage=stage, detail="Widget left the page."
                )
            if time.monotonic() >= deadline:
                return ChallengeResult(
                    status="timeout",
                    stage=stage,
                    detail=(
                        "Interaction was dispatched but no token appeared and the "
                        "widget is still present. The challenge is NOT solved."
                    ),
                )
            await asyncio.sleep(0.4)

    async def _eval(self, expression: str) -> Any:
        result = await self._engine.send(
            "Runtime.evaluate", {"expression": expression, "returnByValue": True}
        )
        return (result or {}).get("result", {}).get("value")

    async def _page_html(self) -> str:
        html = await self._eval("document.documentElement.outerHTML")
        return html if isinstance(html, str) else ""

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
        value = result.get("result", {}).get("value", "")
        return str(value) if value is not None else ""

    async def _get_page_info(self) -> tuple[str, str]:
        result = await self._engine.send("Target.getTargetInfo", {})
        info = result.get("targetInfo", {})
        return info.get("title", ""), info.get("url", "")
