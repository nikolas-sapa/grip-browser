from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import math
import random
import re
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grip.cdp.engine import CDPEngine
from grip.cdp.shadow import (
    CLICK_ELEMENT_JS,
    CLICK_REVEAL_JS,
    CLOSED_SHADOW_PATCH_JS,
    DISCOVER_ELEMENTS_JS,
    PAGE_TEXT_JS,
    PROBE_CLICKABLE_JS,
    READ_CONTENT_JS,
    SCROLL_BOTTOM_JS,
    TYPE_ELEMENT_JS,
    _RESOLVE_JS,
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

logger = logging.getLogger(__name__)

# An element still has to be listed and clickable after its label is cut, so the
# label is replaced rather than the element dropped.
_ELIDED = "[elided: detected instruction-like text]"

# Only a real 'click' listener counts. Page JS cannot introspect its own
# addEventListener calls, so PROBE_CLICKABLE_JS (grip/cdp/shadow.py) only
# ranks and bounds *candidates*; this is the ground truth, decided from CDP
# DOMDebugger.getEventListeners against the live page. Deliberately narrow:
# mousedown/pointerdown-only elements (drag handles, custom scroll targets)
# are excluded rather than guessed at — a false positive here hands the model
# a "clickable" element that does nothing, which is worse than the element
# not appearing at all.
_CLICK_LISTENER_TYPES = frozenset({"click"})


# Wall-clock ceiling on the whole probe pass (JS eval + object resolution +
# every DOMDebugger.getEventListeners call). This is a heuristic add-on to
# snapshot(), never allowed to turn a working snapshot into a failed one — see
# Page._discover_probe_elements.
_PROBE_TIMEOUT_S = 2.0

_PROBE_OBJECT_GROUP = "grip-probe"

# See _ensure_fetch_interception below.
_INTERCEPTED_RESOURCE_TYPES = ("Document", "XHR", "Fetch")

# gripStamp() (grip/cdp/shadow.py) only ever writes 'h' + an incrementing
# counter, but it reuses whatever data-grip-h attribute is already on an
# element rather than overwriting it — so a page that pre-sets its own
# data-grip-h="..." before discovery runs hands that value straight back as a
# "handle". Every place in this file that turns a handle into a
# querySelector('[data-grip-h="..."]') string does so by JS-side
# concatenation (see _RESOLVE_FILE_INPUT_JS, _resolve_probe_object_ids), so an
# untrusted handle is a selector-breakout vector, not just a lookup that fails
# closed. Handles are checked against this pattern at the Python/JS boundary
# and anything else is dropped before it ever reaches a query.
_VALID_HANDLE_RE = re.compile(r"^h\d+$")


def _is_trusted_handle(handle: str) -> bool:
    return bool(_VALID_HANDLE_RE.match(handle))


# click()/type()/select() dispatch the DOM action and return immediately — but
# a click that navigates or fires an XHR-driven re-render hasn't finished
# reacting yet by the time the JS call resolves, and the runner's immediate
# follow-up snapshot() then shows the PRE-change page. The model reads that as
# "nothing happened" and repeats the action. This is a bounded, poll-based
# wait: it returns as soon as two consecutive checks see the same page
# signature (nothing left to settle), so a page that reacts fast pays close
# to nothing, and a page that never quiets down pays no more than the cap.
_SETTLE_TIMEOUT_S = 0.5
_SETTLE_POLL_S = 0.05
_SETTLE_QUIET_POLLS = 2

_SETTLE_SIGNATURE_JS = (
    "JSON.stringify({href: location.href, rs: document.readyState,"
    " n: document.getElementsByTagName('*').length})"
)

# press(): named keys get a real code/windowsVirtualKeyCode pair so a keydown
# listener gated on `event.code` (not just `event.key`) still fires. Values
# are (code, windowsVirtualKeyCode) — windowsVirtualKeyCode is what CDP's
# Input.dispatchKeyEvent uses to pick the native key, independent of the
# `key`/`text` strings.
_NAMED_KEYS: dict[str, tuple[str, int]] = {
    "Enter": ("Enter", 13),
    "Tab": ("Tab", 9),
    "Escape": ("Escape", 27),
    "Backspace": ("Backspace", 8),
    "Delete": ("Delete", 46),
    "ArrowUp": ("ArrowUp", 38),
    "ArrowDown": ("ArrowDown", 40),
    "ArrowLeft": ("ArrowLeft", 37),
    "ArrowRight": ("ArrowRight", 39),
    "Home": ("Home", 36),
    "End": ("End", 35),
    "PageUp": ("PageUp", 33),
    "PageDown": ("PageDown", 34),
    " ": ("Space", 32),
    "Space": ("Space", 32),
}

# Input.dispatchKeyEvent's modifiers bitmask: Alt=1, Ctrl=2, Meta/Cmd=4, Shift=8.
_MODIFIER_BITS = {
    "alt": 1, "option": 1,
    "ctrl": 2, "control": 2,
    "meta": 4, "cmd": 4, "command": 4,
    "shift": 8,
}


def _modifiers_bitmask(modifiers: list[str] | None) -> int:
    if not modifiers:
        return 0
    bits = 0
    for m in modifiers:
        bits |= _MODIFIER_BITS.get(m.lower(), 0)
    return bits


def _has_click_listener(listeners: list[dict[str, Any]]) -> bool:
    """Pure so the false-positive control — a plain container div, or any
    element with only non-click listeners, must not be treated as clickable —
    is unit-testable without a real browser."""
    return any(
        (listener or {}).get("type") in _CLICK_LISTENER_TYPES
        for listener in listeners
    )

# upload() resolves against its own discovery pass rather than the shared
# DISCOVER_ELEMENTS_JS/snapshot pipeline (grip/cdp/shadow.py): that pipeline's
# only text sources are innerText/value/aria-label, and a <input type=file>
# has none of those before a file is chosen — every real form labels a file
# input with an associated <label>, which the shared pipeline never reads.
# Kept deliberately light DOM only (no shadow-root walk): file inputs inside a
# shadow root will not be found here.
_FIND_FILE_INPUTS_JS = """
(function () {
  function stamp(el) {
    let h = el.getAttribute('data-grip-h');
    if (!h) {
      window.__gripHandleSeq = (window.__gripHandleSeq || 0) + 1;
      h = 'h' + window.__gripHandleSeq;
      el.setAttribute('data-grip-h', h);
    }
    return h;
  }
  function labelFor(el) {
    if (el.id) {
      const lbl = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (lbl) return (lbl.innerText || '').trim();
    }
    const wrap = el.closest('label');
    return wrap ? (wrap.innerText || '').trim() : '';
  }
  const out = [];
  document.querySelectorAll('input[type="file"]').forEach(function (el) {
    out.push({
      handle: stamp(el),
      label: labelFor(el),
      aria: el.getAttribute('aria-label') || '',
      name: el.getAttribute('name') || '',
      id: el.id || '',
    });
  });
  return JSON.stringify(out);
})();
"""

# Re-resolves by the same data-grip-h stamp _FIND_FILE_INPUTS_JS assigned,
# this time asking Runtime.evaluate for a RemoteObject (returnByValue=False)
# instead of a JSON value — DOM.setFileInputFiles needs an objectId, not a
# description of the element.
_RESOLVE_FILE_INPUT_JS = """
function (handle) {
  return document.querySelector('[data-grip-h="' + CSS.escape(handle) + '"]');
}
"""

# select()'s own action JS, kept local like _FIND_FILE_INPUTS_JS/
# _RESOLVE_FILE_INPUT_JS above rather than added to grip/cdp/shadow.py
# (out of scope for this change; shadow.py owns discovery + click/type only).
# Reuses _RESOLVE_JS for the same identity-checked handle lookup click()/
# type() use, so a stale or swapped <select> raises the same way theirs does.
#
# Precedence, matched against the visible option list in order:
#   1. exact visible option text (case-insensitive) — what a model reading the
#      snapshot actually sees.
#   2. exact `value` attribute (case-insensitive) — for callers that already
#      know the underlying value.
#   3. a *unique* case-insensitive substring of the visible text — covers a
#      model paraphrasing a label ("Engineer" for "Engineer (Senior)"). A
#      substring matching more than one option is not resolved silently; it
#      is reported as no_such_option with the full option list so the caller
#      can be exact instead of guessing which one was meant.
# Disabled options are skipped at every stage — selecting one is not a real
# user action a <select> allows.
_SELECT_OPTION_JS = """
function(handle, expectedTag, optionValue) {
""" + _RESOLVE_JS + """
  const r = gripResolve(handle, expectedTag, '');
  if (!r.el) return { ok: false, reason: r.reason };
  const el = r.el;
  if (el.tagName.toLowerCase() !== 'select') {
    return { ok: false, reason: 'not_a_select', tag: el.tagName.toLowerCase() };
  }
  const options = Array.prototype.filter.call(el.options, function (o) { return !o.disabled; });
  const wanted = optionValue.trim().toLowerCase();
  let match = null;
  for (const opt of options) {
    if ((opt.text || '').trim().toLowerCase() === wanted) { match = opt; break; }
  }
  if (!match) {
    for (const opt of options) {
      if ((opt.value || '').toLowerCase() === wanted) { match = opt; break; }
    }
  }
  if (!match) {
    const hits = options.filter(function (opt) {
      return (opt.text || '').trim().toLowerCase().includes(wanted);
    });
    if (hits.length === 1) match = hits[0];
  }
  if (!match) {
    return {
      ok: false, reason: 'no_such_option',
      options: options.map(function (o) { return (o.text || '').trim(); }),
    };
  }
  el.selectedIndex = match.index;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return { ok: true, reason: '' };
}
"""


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


# scroll()'s own action JS, kept local like _SELECT_OPTION_JS/_FIND_FILE_INPUTS_JS
# above rather than added to grip/cdp/shadow.py (out of scope for this change).
_SCROLL_BY_JS = """
function (direction, pages) {
  var vw = window.innerWidth, vh = window.innerHeight;
  var dx = 0, dy = 0;
  if (direction === 'down') dy = vh * pages;
  else if (direction === 'up') dy = -vh * pages;
  else if (direction === 'right') dx = vw * pages;
  else if (direction === 'left') dx = -vw * pages;
  window.scrollBy(dx, dy);
  var doc = document.documentElement;
  return {
    ok: true,
    x: window.scrollX, y: window.scrollY,
    pageHeight: doc.scrollHeight, pageWidth: doc.scrollWidth,
    viewportHeight: vh, viewportWidth: vw
  };
}
"""

# Reuses _RESOLVE_JS for the same identity-checked handle lookup click()/
# type()/_SELECT_OPTION_JS use, so a stale or swapped ref raises the same way
# theirs does rather than scrolling to whatever now occupies the handle.
_SCROLL_TO_REF_JS = """
function(handle, expectedTag, expectedText) {
""" + _RESOLVE_JS + """
  const r = gripResolve(handle, expectedTag, expectedText);
  if (!r.el) return { ok: false, reason: r.reason };
  r.el.scrollIntoView({ block: 'center', inline: 'nearest' });
  var doc = document.documentElement;
  return {
    ok: true,
    x: window.scrollX, y: window.scrollY,
    pageHeight: doc.scrollHeight, pageWidth: doc.scrollWidth,
    viewportHeight: window.innerHeight, viewportWidth: window.innerWidth
  };
}
"""

# Read-only scroll metrics folded into every snapshot() — see
# Page._get_scroll_metrics and the snapshot.scroll_* attributes it sets.
_SCROLL_METRICS_JS = """
(function () {
  var doc = document.documentElement;
  return JSON.stringify({
    x: window.scrollX, y: window.scrollY,
    pageHeight: doc.scrollHeight, pageWidth: doc.scrollWidth,
    viewportHeight: window.innerHeight, viewportWidth: window.innerWidth
  });
})();
"""


# wait_for()'s own JS, kept local like _SELECT_OPTION_JS/_FIND_FILE_INPUTS_JS
# above — each check is one bounded Runtime.evaluate, not a full snapshot(),
# so polling stays cheap. See Page.wait_for() for what each kind means.
_WAIT_TEXT_JS = """
function (needle) {
  var body = document.body;
  if (!body) return false;
  return (body.innerText || '').toLowerCase().indexOf(needle.toLowerCase()) !== -1;
}
"""

# Restricted to elements a click()/type() target would actually resolve to,
# not any prose containing the text — the same "is this a target, not a
# paragraph" distinction _resolve_target's substring match makes.
_WAIT_ELEMENT_JS = """
function (needle) {
  var want = needle.toLowerCase();
  var nodes = document.querySelectorAll(
    'a,button,input,select,textarea,[role],[onclick],[tabindex]'
  );
  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    var text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
    if (text.toLowerCase().indexOf(want) !== -1) return true;
  }
  return false;
}
"""

_WAIT_SELECTOR_JS = """
function (selector) {
  try { return !!document.querySelector(selector); }
  catch (e) { return false; }
}
"""

# Consent-wall dismissal (Page._maybe_dismiss_consent_banner): matched by
# EXACT normalized text against a small allowlist, not substring-anywhere —
# "accept" as a substring also hits "Accept terms and delete my account",
# and a false-positive click here is worse than leaving the banner up (see
# the audit note this is built from). Only visible button-like elements are
# candidates; the first match wins.
_CONSENT_ACCEPT_PHRASES = (
    "accept", "accept all", "accept all cookies", "accept cookies",
    "i agree", "agree", "allow all", "allow all cookies", "got it", "ok",
)

_CONSENT_DISMISS_JS = """
function (phrases) {
  var nodes = document.querySelectorAll('button, a[role="button"], [role="button"]');
  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    var rect = el.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) continue;
    var text = (el.innerText || el.textContent || '').trim().toLowerCase();
    if (phrases.indexOf(text) !== -1) {
      el.click();
      return { clicked: true, text: text };
    }
  }
  return { clicked: false, text: '' };
}
"""

# Page.javascriptDialogOpening policy default (Page._ensure_dialog_handling):
# alert/confirm/beforeunload are accepted — a page's own confirm()/alert() is
# not something an automated caller can answer differently, and refusing
# beforeunload would leave every link click hanging on "leave this page?".
# prompt() is dismissed rather than accepted with a synthesized answer — a
# page asking a free-text question has no safe default value, and answering
# with an empty string reads to the page as a real (if blank) user response
# rather than "no answer given".
_DEFAULT_DIALOG_POLICY: dict[str, bool] = {
    "alert": True, "confirm": True, "beforeunload": True, "prompt": False,
}


@dataclass
class PopupInfo:
    """What Page can tell a caller about a window.open()/target="_blank"
    popup opened under `NavigationPolicy(allow_popups=True)` — see
    Page.wait_for_popup().

    Deliberately not a full child Page. CDPEngine (grip/cdp/engine.py)
    dispatches every event by method name only (see its _receive_forever),
    with no session-scoped routing — a Page layered on this page's shared
    connection would have its listener-based features (goto()'s load wait,
    dialog handling, download tracking, same-document nav invalidation) fed
    events from BOTH targets indiscriminately. A real child Page needs
    either its own websocket (which needs connection details — host, port,
    cdp_url — that only Browser holds) or session-scoped event demuxing in
    CDPEngine; this file owns neither. target_id/url/session_id is the
    addressable half: enough for code that does hold a Browser to open a
    genuinely independent Page onto the popup (e.g. `browser.open(info.url)`
    for a same-origin OAuth redirect), without this object pretending to
    already be one.
    """
    target_id: str
    url: str
    session_id: str


@dataclass
class ScrollPosition:
    """Viewport scroll offset plus document/viewport size — what a caller
    needs to know "am I near the bottom" / "is there more below the fold"
    without a screenshot. Returned by Page.scroll() and mirrored onto every
    PageSnapshot as scroll_top/scroll_left/scroll_height/client_height (see
    Page.snapshot() and PageSnapshot in grip/compression/summarizer.py).
    page_width/viewport_width have no PageSnapshot counterpart yet — only
    vertical scroll is reported there, per the summarizer's own "horizontal
    scroll is rare" call (Summarizer._format_viewport_line)."""
    x: int
    y: int
    page_height: int
    page_width: int
    viewport_height: int
    viewport_width: int


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
        settle_timeout: float = _SETTLE_TIMEOUT_S,
        dialog_policy: dict[str, bool] | None = None,
        dismiss_consent_banners: bool = True,
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
        # Cap for _settle()'s post-action wait — see _SETTLE_TIMEOUT_S.
        self._settle_timeout = settle_timeout
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
        # Programmatic visibility into blocking a caller can't otherwise see —
        # see popups_blocked and _on_target_attached below.
        self._popups_blocked = 0
        # Fire-and-forget tasks spawned from synchronous CDP event handlers
        # (_on_fetch_paused, _on_target_attached) below, which cannot await
        # directly. asyncio only holds a weak reference to a task started via
        # ensure_future/create_task, so without this the task can be
        # garbage-collected mid-flight — silently dropping a
        # Fetch.continueRequest/failRequest or a Target.closeTarget/
        # runIfWaitingForDebugger call and hanging the request/target it was
        # meant to resolve.
        self._bg_tasks: set[asyncio.Task[None]] = set()
        # Download tracking (see enable_downloads()/wait_for_download()).
        # armed once per page lifetime, same reasoning as _fetch_enabled above
        # — a second enable_downloads() call (a new directory) just updates
        # the Browser-domain target, it doesn't need a second listener.
        self._download_dir: Path | None = None
        self._download_events_armed = False
        self._download_queue: asyncio.Queue[Path | None] | None = None
        # Page-domain enable, shared by every feature below that needs it
        # (dialogs, nav invalidation, file chooser interception) and by
        # goto(), which already sends it directly — see _ensure_page_domain().
        self._page_domain_enabled = False
        # Closed-shadow-root patch (see _ensure_closed_shadow_patch): armed
        # once per page lifetime — Page.addScriptToEvaluateOnNewDocument is
        # re-applied by CDP on every navigation of this target automatically.
        self._closed_shadow_patch_armed = False
        # Dialog handling (see _ensure_dialog_handling): armed once per page
        # lifetime, same "once, not per-navigation" reasoning as
        # _fetch_enabled above — Page.enable applies for the page's whole
        # life, not just the current document.
        self._dialog_handling_armed = False
        self._dialog_policy: dict[str, bool] = {
            **_DEFAULT_DIALOG_POLICY, **(dialog_policy or {}),
        }
        # Surfaced via consume_dialogs() — see _on_dialog_opening. A dialog is
        # otherwise silent: Page.handleJavaScriptDialog answers it, but
        # nothing tells the caller a question was even asked.
        self._pending_dialogs: list[dict[str, Any]] = []
        # Same-document navigation invalidation (see _ensure_nav_invalidation)
        # and consent-banner dismissal share this arming: an SPA route change
        # both stales the cached snapshot and re-opens the door for a new
        # cookie wall, so one event handler resets both.
        self._nav_invalidation_armed = False
        self._dismiss_consent_banners = dismiss_consent_banners
        self._consent_dismissed_this_nav = False
        # Popup adoption (see _on_target_attached, wait_for_popup): populated
        # only when NavigationPolicy(allow_popups=True) — see PopupInfo.
        self._popup_queue: asyncio.Queue[PopupInfo] = asyncio.Queue()

    @property
    def popups_blocked(self) -> int:
        """Count of window.open()/target="_blank" attempts refused by popup
        blocking (see _ensure_popup_blocking) over this Page's lifetime. Zero
        under `NavigationPolicy(allow_popups=True)`, since blocking is never
        armed there. The programmatic half of "why did nothing happen when I
        clicked Login" — pair with the WARNING-level log line at the point of
        each block."""
        return self._popups_blocked

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
        await self._ensure_dialog_handling()
        await self._ensure_nav_invalidation()
        await self._ensure_closed_shadow_patch()

    async def _ensure_closed_shadow_patch(self) -> None:
        """Registers CLOSED_SHADOW_PATCH_JS (grip/cdp/shadow.py) via
        Page.addScriptToEvaluateOnNewDocument, so a closed shadow root
        created during a page's very first render is captured before
        DISCOVER_ELEMENTS_JS's tree walk ever runs — see that constant's own
        docstring for why this has to be the CDP "before any script" hook,
        not a Runtime.evaluate reachable only after load.

        Armed once per Page lifetime, same reasoning as
        _ensure_fetch_interception above: Page.addScriptToEvaluateOnNewDocument
        is re-applied by CDP on every navigation of this target automatically,
        so a second registration would just double-run the (idempotent)
        patch, not extend its coverage.
        """
        if self._closed_shadow_patch_armed:
            return
        self._closed_shadow_patch_armed = True
        await self._engine.send(
            "Page.addScriptToEvaluateOnNewDocument", {"source": CLOSED_SHADOW_PATCH_JS}
        )

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
            # Scoped to the resource types the policy actually needs to see.
            # "*" (any type) paused every subresource a page loads — image,
            # font, CSS, analytics beacon — each costing a Fetch.requestPaused
            # round trip plus a background continueRequest task for a request
            # NavigationPolicy was never going to refuse anyway (only a
            # document/XHR/fetch URL can carry the caller to a private/
            # metadata host). Document covers the top-level navigation AND
            # every redirect leg AND sub-frame navigations (each pauses again
            # with resourceType "Document" — see _on_fetch_paused's is_main_frame
            # check); XHR/Fetch cover page JS calling out after load. Anything
            # else (Image, Stylesheet, Font, Media, ...) is not intercepted at
            # all and passes straight through.
            {"patterns": [
                {"urlPattern": "*", "resourceType": rt, "requestStage": "Request"}
                for rt in _INTERCEPTED_RESOURCE_TYPES
            ]},
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

    async def _ensure_page_domain(self) -> None:
        """Page.enable, once per page lifetime. goto() already sends it
        directly as part of its own gather (see there); this covers every
        other entry point — dialogs, nav invalidation, file chooser
        interception — for a Page reached without goto() (remote CDP
        attach, an adopted target, or any call before the first goto())."""
        if self._page_domain_enabled:
            return
        self._page_domain_enabled = True
        await self._engine.send("Page.enable")

    async def _ensure_dialog_handling(self) -> None:
        """Subscribes to Page.javascriptDialogOpening so a confirm()/alert()/
        beforeunload the page raises is answered automatically instead of
        freezing the tab until CDPEngine's own send() timeout — nothing
        answers a dialog otherwise, and Chrome will not process another
        command on this target while one is open. See _DEFAULT_DIALOG_POLICY
        for the default answer to each dialog type and _on_dialog_opening for
        how it's surfaced to the caller afterward."""
        if self._dialog_handling_armed:
            return
        self._dialog_handling_armed = True
        await self._ensure_page_domain()
        self._engine.on("Page.javascriptDialogOpening", self._on_dialog_opening)

    def _on_dialog_opening(self, params: dict[str, Any]) -> None:
        """Runs synchronously (CDPEngine dispatches listeners inline) and
        hands the actual Page.handleJavaScriptDialog call off to the event
        loop — same shape as _on_fetch_paused above."""
        dialog_type = params.get("type", "")
        message = params.get("message", "")
        accept = self._dialog_policy.get(dialog_type, True)
        logger.info(
            "javascript dialog %r auto-%s: %r",
            dialog_type, "accepted" if accept else "dismissed", message,
        )
        self._pending_dialogs.append({
            "type": dialog_type, "message": message, "accepted": accept,
        })
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="dialog",
            input={"type": dialog_type, "message": message},
            output={"accepted": accept},
            tokens_consumed=0,
            duration_ms=0,
        ))
        args: dict[str, Any] = {"accept": accept}
        if dialog_type == "prompt" and accept:
            args["promptText"] = ""
        self._spawn_bg(self._handle_dialog(args))

    async def _handle_dialog(self, args: dict[str, Any]) -> None:
        # Best-effort like _continue_fetch/_fail_fetch — the target can be
        # gone (tab closed from under the dialog) by the time this runs.
        with contextlib.suppress(Exception):
            await self._engine.send("Page.handleJavaScriptDialog", args)

    def consume_dialogs(self) -> list[dict[str, Any]]:
        """Every javascript dialog auto-answered since the last call to this,
        as `{"type", "message", "accepted"}` dicts, oldest first. Draining
        rather than peeking: a dialog is meant to be surfaced to the caller
        exactly once — see grip.mcp.server / Runner, which call this after
        every action and prepend a note to the tool result when it's
        non-empty, so "why did nothing happen when I clicked Login" has an
        answer instead of a silently swallowed confirm()."""
        dialogs, self._pending_dialogs = self._pending_dialogs, []
        return dialogs

    async def _ensure_nav_invalidation(self) -> None:
        """Subscribes to Page.frameNavigated (a full commit, main-frame-only)
        and Page.navigatedWithinDocument (pushState/replaceState/hash change)
        so a same-document SPA navigation invalidates the cached snapshot the
        same way goto() already does for a full one (see goto()'s own resets
        at the top of that method) — without this, a route change left the
        old snapshot's refs/handles looking valid while describing a DOM that
        may no longer exist, and a delta built against it would diff two
        different documents."""
        if self._nav_invalidation_armed:
            return
        self._nav_invalidation_armed = True
        await self._ensure_page_domain()
        self._engine.on("Page.frameNavigated", self._on_frame_navigated)
        self._engine.on(
            "Page.navigatedWithinDocument", self._on_navigated_within_document
        )

    def _on_frame_navigated(self, params: dict[str, Any]) -> None:
        # frameNavigated fires for every frame, including iframes navigating
        # on their own — a frame with a parentId is not this page's own
        # top-level document. Also fires for goto()'s own navigations; that's
        # a harmless redundant reset (the fields are already None by then),
        # not a bug — see goto()'s own resets at the top of that method.
        frame = params.get("frame", {})
        if frame.get("parentId"):
            return
        self._invalidate_snapshot_cache()

    def _on_navigated_within_document(self, params: dict[str, Any]) -> None:
        # navigatedWithinDocument carries frameId directly (no nested frame
        # dict to read a parentId off), so this is scoped the same way
        # _on_fetch_paused's is_main_frame check is: compared against this
        # page's own target id, with an empty target_id (a Page built
        # without going through Browser.open()) falling back to "no id to
        # compare, treat as main" rather than never firing at all.
        frame_id = params.get("frameId", "")
        if self._target_id and frame_id != self._target_id:
            return
        self._invalidate_snapshot_cache()

    def _invalidate_snapshot_cache(self) -> None:
        self._current_snapshot = None
        self._previous_snapshot = None
        self.delta = None
        # A new document (or a new SPA "page" within the same document) gets
        # its own chance at a consent-wall dismissal — see
        # _maybe_dismiss_consent_banner.
        self._consent_dismissed_this_nav = False

    async def _maybe_dismiss_consent_banner(self) -> None:
        """Best-effort, once per navigation (see _invalidate_snapshot_cache):
        click a cookie/consent banner's accept button before the caller's
        next read of the page, so a wall that would otherwise block every
        click doesn't have to be discovered by trial and error. Opt out via
        `Page(..., dismiss_consent_banners=False)`. Never allowed to fail the
        caller — same reasoning as _discover_probe_elements: this is a
        heuristic add-on to snapshot(), not something it depends on."""
        if not self._dismiss_consent_banners or self._consent_dismissed_this_nav:
            return
        self._consent_dismissed_this_nav = True
        try:
            outcome = await self._eval(
                f"({_CONSENT_DISMISS_JS})({json.dumps(_CONSENT_ACCEPT_PHRASES)})"
            )
        except Exception:
            return
        if not isinstance(outcome, dict) or not outcome.get("clicked"):
            return
        text = outcome.get("text", "")
        logger.info("consent banner dismissed: clicked button labeled %r", text)
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="consent_dismissed",
            input={},
            output={"text": text},
            tokens_consumed=0,
            duration_ms=0,
        ))
        await self._settle()

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
        caller has opted into allow_private. Still armed under
        `NavigationPolicy(allow_popups=True)` — unlike before, when auto-attach
        was never armed at all under that flag and a popup went completely
        unobserved. It is now paused just long enough to record its
        target_id/url/session_id (see _on_target_attached, PopupInfo) and
        immediately resumed — a transparent pause-and-go, not a hold — so
        `wait_for_popup()` has something to return. Fetch-domain enforcement
        inside the popup is still not armed either way; see that flag's
        docstring for what accepting it costs.
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
            popup_url = target_info.get("url", "")
            if not self._policy.allow_popups:
                # A blocked popup is otherwise silent: the target is closed
                # before it runs any JS, and the caller who clicked "Login"
                # just sees nothing happen. Make it legible — a log line to
                # explain it, plus a counter and a Trace entry so it's also
                # visible to code, not just a human reading logs.
                self._popups_blocked += 1
                logger.warning(
                    "popup blocked: window.open()/target=_blank to %r was "
                    "refused (NavigationPolicy.allow_popups=False, the "
                    "default) — pass allow_popups=True to permit popups, at "
                    "the cost of Fetch interception inside them",
                    popup_url,
                )
                self._trace.add(TraceEntry(
                    timestamp=time.time(),
                    action="popup_blocked",
                    input={"url": popup_url},
                    output={},
                    tokens_consumed=0,
                    duration_ms=0,
                ))
                if target_id:
                    self._spawn_bg(self._close_popup_target(target_id))
                return
            # allow_popups=True: record it for wait_for_popup() (see
            # PopupInfo for what this can and cannot give the caller) and
            # resume it — same as any other attached target below.
            self._trace.add(TraceEntry(
                timestamp=time.time(),
                action="popup_opened",
                input={},
                output={"url": popup_url, "target_id": target_id},
                tokens_consumed=0,
                duration_ms=0,
            ))
            self._popup_queue.put_nowait(
                PopupInfo(target_id=target_id, url=popup_url, session_id=session_id)
            )
            self._spawn_bg(self._resume_attached_target(session_id))
            return
        self._spawn_bg(self._resume_attached_target(session_id))

    async def wait_for_popup(self, timeout: float = 10.0) -> PopupInfo:
        """Wait for the next popup this page opens under
        `NavigationPolicy(allow_popups=True)` — see PopupInfo's docstring for
        exactly what this can and cannot give the caller. Raises a typed
        NETWORK_TIMEOUT (see wait_for()'s matching one) if none opens in
        time."""
        if not self._policy.allow_popups:
            raise ValueError(
                "wait_for_popup() needs NavigationPolicy(allow_popups=True) "
                "— with the default policy every popup is blocked outright "
                "(see Page.popups_blocked)."
            )
        await self._ensure_popup_blocking()
        try:
            async with asyncio.timeout(timeout):
                return await self._popup_queue.get()
        except TimeoutError as e:
            raise GripError(BrowserError(
                type=ErrorType.NETWORK_TIMEOUT,
                message=f"No popup opened within {timeout}s.",
                confidence=0.6,
                recovery=[RecoveryAction.RETRY],
            )) from e

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
        # Set from Network.loadingFailed for the main-frame document request —
        # a DNS failure, connection refused, or a Fetch-domain block reaching
        # the network layer (net::ERR_*). Previously nothing observed this
        # event at all: a page whose document never loaded still hit
        # `await load_event.wait()`, timed out, and the bare `except
        # TimeoutError: pass` below swallowed it — goto() returned as if it
        # had succeeded, with _status_code left at 0 and no signal a caller
        # could act on.
        network_error: str | None = None

        def on_load(_params: dict[str, Any]) -> None:
            load_event.set()

        def on_response(params: dict[str, Any]) -> None:
            # Only the main document response carries the status that describes the
            # fetch. Sub-resources (images, XHR) fire this too and must be ignored.
            # Redirect chains fire several Document responses; the last one wins.
            if params.get("type") == "Document":
                self._status_code = params.get("response", {}).get("status", 0)

        def on_loading_failed(params: dict[str, Any]) -> None:
            # type == "Document" excludes ordinary sub-resource failures (an
            # image 404, a blocked tracking pixel) — those are not this
            # navigation failing. Network.loadingFailed carries no frameId to
            # further exclude a failed sub-frame the way _on_fetch_paused's
            # is_main_frame check does for Fetch.requestPaused; a failed
            # iframe document load is the one case this can misattribute to
            # the top-level navigation.
            nonlocal network_error
            if (
                network_error is None
                and params.get("type") == "Document"
                and not params.get("canceled")
            ):
                network_error = params.get("errorText") or "unknown network error"
                load_event.set()

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
        self._engine.on("Network.loadingFailed", on_loading_failed)
        # Only this goto() cares about a refused top-level document; the
        # Fetch handler itself lives for the page's whole lifetime.
        self._doc_refusal_hook = on_document_refused
        timed_out = False
        try:
            async with asyncio.timeout(timeout):
                # Runtime goes up with the other two rather than lazily in
                # snapshot(): a page handed back by goto() has to be usable, and
                # enabling Runtime after the fact costs a round trip on the hot path.
                await asyncio.gather(
                    self._ensure_page_domain(),
                    self._engine.send("Network.enable"),
                    self._engine.send("Runtime.enable"),
                    self._ensure_fetch_interception(),
                    self._ensure_popup_blocking(),
                    self._ensure_dialog_handling(),
                    self._ensure_nav_invalidation(),
                    self._ensure_closed_shadow_patch(),
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
                    await self._maybe_dismiss_consent_banner()
                    return
                await self._engine.send("Page.navigate", {"url": url})
                await load_event.wait()
        except TimeoutError:
            # Not swallowed outright any more (see below) — but a slow page
            # that DID get a response is still a usable page, so this alone
            # isn't the failure signal. A dead connection is not caught here
            # either — CDPEngine.send() raises GripError(ErrorType.
            # BROWSER_CRASHED) for a lost socket or Inspector.targetCrashed
            # (not the plain ConnectionError this comment used to describe),
            # and that is deliberately left to propagate: it is already a
            # typed, caller-visible error and turning it into anything else
            # here would only throw away the more specific signal.
            timed_out = True
        finally:
            self._engine.off("Page.loadEventFired", on_load)
            self._engine.off("Network.responseReceived", on_response)
            self._engine.off("Network.loadingFailed", on_loading_failed)
            self._doc_refusal_hook = None
        if refused_url is not None:
            enforce_navigation(self._policy, refused_url)
        if network_error is not None:
            raise GripError(BrowserError(
                type=ErrorType.NAVIGATION_FAILED,
                message=f"Navigation to {url!r} failed: {network_error}",
                confidence=0.9,
                recovery=[RecoveryAction.RETRY, RecoveryAction.EXPONENTIAL_BACKOFF],
            ))
        if timed_out and self._status_code == 0:
            # Nothing ever came back for the top-level document within
            # `timeout` — not a slow "load" event on an otherwise-fetched
            # page (that case has status_code set and is left alone), but no
            # response at all. Previously this returned as if goto() had
            # succeeded, with _status_code left at 0 and no signal a caller
            # could act on.
            raise GripError(BrowserError(
                type=ErrorType.NETWORK_TIMEOUT,
                message=(
                    f"Navigation to {url!r} timed out after {timeout}s with no "
                    "response for the top-level document."
                ),
                confidence=0.7,
                recovery=[RecoveryAction.RETRY, RecoveryAction.EXPONENTIAL_BACKOFF],
            ))
        # Best-effort, once per navigation (see _invalidate_snapshot_cache,
        # armed above by Page.frameNavigated) — a fresh document is exactly
        # when a cookie/consent wall shows up. Only reached once loading has
        # actually settled (a raise above skips it, same as any other
        # post-navigation step would).
        await self._maybe_dismiss_consent_banner()

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
            (
                raw_elements, page_text, (title, url), probe_elements, scroll,
            ) = await asyncio.gather(
                self._discover_elements(), self._get_page_text(), self._get_page_info(),
                self._discover_probe_elements(), self._get_scroll_metrics(),
            )
        except GripError:
            # Already typed — e.g. ErrorType.BROWSER_CRASHED from a lost CDP
            # connection or Inspector.targetCrashed (CDPEngine.send()).
            # Re-classifying it below by string-matching str(e) would lose
            # that and misreport a crashed browser as ELEMENT_NOT_FOUND with
            # a RE_SNAPSHOT recovery hint — looping the caller straight back
            # into the dead connection.
            raise
        except Exception as e:
            err = self._classifier.classify_cdp_error(str(e))
            raise GripError(err) from e

        # Appended after the semantic elements, not merged in document order:
        # every existing element keeps its index, so callers matching by
        # earlier snapshot position are unaffected, and a real button/link
        # still wins over a same-text div in _find_element's first-match scan.
        raw_elements = raw_elements + probe_elements

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
        # PageSnapshot.scroll_top/scroll_left/scroll_height/client_height are
        # real dataclass fields (grip/compression/summarizer.py) — the
        # renderer keys off scroll_height <= 0 to omit the VIEWPORT line for
        # snapshots that predate this (a directly-built PageSnapshot in a
        # test, or a caller stuck on an older Summarizer.build()).
        snapshot.scroll_top = scroll.y
        snapshot.scroll_left = scroll.x
        snapshot.scroll_height = scroll.page_height
        snapshot.client_height = scroll.viewport_height
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
        except GripError:
            # See snapshot()'s matching except GripError: raise — don't
            # re-classify an already-typed error (e.g. BROWSER_CRASHED) by
            # string-matching its message.
            raise
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

    async def _page_signature(self) -> str | None:
        """Cheap, best-effort fingerprint used only by _settle() to notice
        change. None on any failure — including the CDP errors a navigation's
        context teardown throws mid-flight, which is exactly the moment
        _settle() is watching for and must not blow up on."""
        with contextlib.suppress(Exception):
            sig = await self._eval(_SETTLE_SIGNATURE_JS)
            return sig if isinstance(sig, str) else None
        return None

    async def _retry_after_stale(self, outcome: dict[str, Any]) -> bool:
        """One re-snapshot-and-retry for a same-document re-render between
        snapshot() and dispatch (an SPA re-rendering the row a click/type/
        select target lived in), so a transient miss doesn't cost the LLM a
        whole extra turn just to re-snapshot and try again itself.

        Only "not_found"/"identity_mismatch" are retried — a wrong element
        kind or a missing <select> option is not made right by re-resolving
        the same description, and retrying it would just repeat the same
        failure after paying for another snapshot.

        Does not weaken the stale-ref rejection in _find_element/_find_input/
        _find_select: snapshot() resets the ref registry on a URL change (see
        RefRegistry.reset()), so this always re-resolves against the same
        document the caller was already acting on, never across a navigation.
        """
        if outcome.get("reason") not in ("not_found", "identity_mismatch"):
            return False
        await self.snapshot()
        return True

    async def _settle(self, timeout: float | None = None) -> None:
        """Bounded wait after a click/type/select dispatch for the page to
        react — a navigation or an XHR-driven DOM update that hasn't finished
        by the time the dispatch call returns. Short-circuits the moment the
        page signature stops changing for two consecutive polls, so a page
        that reacted instantly (or not at all) pays close to nothing; only a
        page still mutating at the deadline pays the full cap.
        """
        deadline = time.monotonic() + (self._settle_timeout if timeout is None else timeout)
        prev_sig = await self._page_signature()
        quiet_polls = 0
        while time.monotonic() < deadline:
            await asyncio.sleep(_SETTLE_POLL_S)
            sig = await self._page_signature()
            if sig == prev_sig:
                quiet_polls += 1
                if quiet_polls >= _SETTLE_QUIET_POLLS:
                    return
            else:
                quiet_polls = 0
                prev_sig = sig

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
        if not outcome.get("ok") and await self._retry_after_stale(outcome):
            el = self._find_element(description)
            if el is None:
                raise GripError(self._classifier.classify_semantic_miss(description))
            js = (
                f"({CLICK_ELEMENT_JS})"
                f"({json.dumps(el.handle)}, {json.dumps(el.tag)}, {json.dumps(el.text)})"
            )
            result = await self._engine.send(
                "Runtime.evaluate", {"expression": js, "returnByValue": True}
            )
            outcome = result.get("result", {}).get("value") or {}
        if outcome.get("ok"):
            # A navigation or XHR-driven update triggered by this click may
            # still be in flight — settle before the caller's next snapshot()
            # sees a stale, pre-change page. Included in this action's own
            # duration_ms, since it is real wall-clock time the click cost.
            await self._settle()
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
        if not outcome.get("ok") and await self._retry_after_stale(outcome):
            el = self._find_input(description)
            if el is None:
                raise GripError(self._classifier.classify_semantic_miss(description))
            js = (
                f"({TYPE_ELEMENT_JS})"
                f"({json.dumps(el.handle)}, {json.dumps(text)}, "
                f"{json.dumps(el.tag)}, {json.dumps(el.text)})"
            )
            result = await self._engine.send(
                "Runtime.evaluate", {"expression": js, "returnByValue": True}
            )
            outcome = result.get("result", {}).get("value") or {}
        if outcome.get("ok"):
            # See click() — a submit-on-Enter or a live-search XHR can react
            # to a type() just as easily as to a click().
            await self._settle()
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

    async def select(self, description: str, value: str) -> None:
        """Choose an option in a `<select>` matched by fuzzy description, the
        same resolution `click()`/`type()` use.

        `value` is matched against the dropdown's own options — visible text
        first, then the `value` attribute, then a unique substring of the
        text — see `_SELECT_OPTION_JS` for the exact ladder. Text wins over
        value because an LLM reads the label a user sees, not the markup
        underneath it.

        Sets `selectedIndex` and dispatches `input`/`change` with
        `bubbles: true` — the events a real user's choice produces — so a
        framework-bound `<select>` (React/Vue controlled component) reacts
        the same as a plain HTML one; a bare value assignment does not fire
        either event and such a component would never see the change.

        `<select multiple>`: only ever resolves to a single option (whichever
        the ladder above matches) and does not accept a list — selecting
        several values in one call needs its own API and is not implemented
        here.
        """
        self._assert_not_safe("select")
        if not self._current_snapshot:
            await self.snapshot()
        t0 = time.monotonic()
        el = self._find_select(description)
        if el is None:
            # Not a real <select> — try a non-native combobox (role=combobox/
            # aria-haspopup, reported by grip/cdp/shadow.py's
            # gripComboboxInfo as Element.is_combobox) before hard-failing.
            # A custom dropdown widget has no <select> for _SELECT_OPTION_JS
            # to even resolve against, so this has to be a different action
            # entirely: open it, re-snapshot, click the option.
            combo = self._find_combobox(description)
            if combo is not None:
                await self._select_combobox(combo, value, t0)
                return
            err = self._classifier.classify_semantic_miss(description)
            raise GripError(err)
        js = (
            f"({_SELECT_OPTION_JS})"
            f"({json.dumps(el.handle)}, {json.dumps(el.tag)}, {json.dumps(value)})"
        )
        result = await self._engine.send(
            "Runtime.evaluate", {"expression": js, "returnByValue": True}
        )
        outcome = result.get("result", {}).get("value") or {}
        if not outcome.get("ok") and await self._retry_after_stale(outcome):
            el = self._find_select(description)
            if el is None:
                raise GripError(self._classifier.classify_semantic_miss(description))
            js = (
                f"({_SELECT_OPTION_JS})"
                f"({json.dumps(el.handle)}, {json.dumps(el.tag)}, {json.dumps(value)})"
            )
            result = await self._engine.send(
                "Runtime.evaluate", {"expression": js, "returnByValue": True}
            )
            outcome = result.get("result", {}).get("value") or {}
        if outcome.get("ok"):
            # See click() — a controlled <select> often re-renders the page
            # (dependent fields, a filtered list) on 'change'.
            await self._settle()
        duration_ms = int((time.monotonic() - t0) * 1000)
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="select",
            input={"description": description, "value": value, "handle": el.handle},
            output={"success": bool(outcome.get("ok")),
                    "reason": outcome.get("reason", "")},
            tokens_consumed=0,
            duration_ms=duration_ms,
        ))
        self._raise_for_select(outcome, description, value)

    async def scroll(
        self, direction: str = "down", pages: float = 1.0, *, ref: str | None = None,
    ) -> ScrollPosition:
        """Scroll the viewport, or bring a specific element into view.

        `direction`/`pages` scroll relative to the current position, in units
        of one viewport (`pages=1.0` is a full page down/up/left/right).
        Pass `ref` — an exact ref or the same fuzzy description click()/
        type() accept — to scroll that element into view instead; `direction`
        and `pages` are ignored when `ref` is given. This is the primitive
        for reaching lazy-loaded content a snapshot can't otherwise see.
        """
        self._assert_not_safe("scroll")
        if not self._current_snapshot:
            await self.snapshot()
        t0 = time.monotonic()
        if ref is not None:
            el = self._find_element(ref)
            if el is None:
                raise GripError(self._classifier.classify_semantic_miss(ref))
            js = (
                f"({_SCROLL_TO_REF_JS})"
                f"({json.dumps(el.handle)}, {json.dumps(el.tag)}, {json.dumps(el.text)})"
            )
        else:
            if direction not in ("up", "down", "left", "right"):
                raise ValueError(f"scroll(): unknown direction {direction!r}")
            js = f"({_SCROLL_BY_JS})({json.dumps(direction)}, {pages})"
        outcome = await self._eval(js) or {}
        if not outcome.get("ok"):
            raise GripError(BrowserError(
                type=ErrorType.ELEMENT_STALE,
                message=(
                    f"Element for {ref!r} no longer matches the snapshot it was "
                    f"found in ({outcome.get('reason') or 'unknown'}). "
                    "Re-snapshot and retry."
                ),
                confidence=1.0,
                recovery=[RecoveryAction.RE_SNAPSHOT],
            ))
        pos = ScrollPosition(
            x=int(outcome["x"]), y=int(outcome["y"]),
            page_height=int(outcome["pageHeight"]), page_width=int(outcome["pageWidth"]),
            viewport_height=int(outcome["viewportHeight"]),
            viewport_width=int(outcome["viewportWidth"]),
        )
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="scroll",
            input={"direction": direction, "pages": pages, "ref": ref},
            output={"x": pos.x, "y": pos.y, "page_height": pos.page_height},
            tokens_consumed=0,
            duration_ms=int((time.monotonic() - t0) * 1000),
        ))
        return pos

    async def _get_scroll_metrics(self) -> ScrollPosition:
        """Read-only companion to scroll() folded into every snapshot() gather
        (see there). Best-effort like _discover_probe_elements: any failure —
        including a mock/test double with nothing left to give it — degrades
        to an all-zero position rather than failing the snapshot over a
        heuristic add-on.
        """
        try:
            raw = await self._eval(_SCROLL_METRICS_JS)
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        return ScrollPosition(
            x=int(data.get("x", 0) or 0),
            y=int(data.get("y", 0) or 0),
            page_height=int(data.get("pageHeight", 0) or 0),
            page_width=int(data.get("pageWidth", 0) or 0),
            viewport_height=int(data.get("viewportHeight", 0) or 0),
            viewport_width=int(data.get("viewportWidth", 0) or 0),
        )

    async def wait_for(
        self,
        *,
        text: str | None = None,
        ref: str | None = None,
        selector: str | None = None,
        timeout: float = 10.0,
        poll_interval: float = 0.25,
    ) -> None:
        """Block until a condition on the live page becomes true, then
        re-snapshot — the primitive for an SPA route change or an
        XHR-driven update that Page.loadEventFired (goto()'s own wait) never
        sees, since neither fires a new load event.

        Exactly one of:
          text: a case-insensitive substring appears anywhere in the page's
            visible text (document.body.innerText) — waiting for prose or a
            status message.
          ref: a case-insensitive substring appears in an *element's* own
            text/value/aria-label (a click()/type() target, not any
            paragraph containing it) — waiting for a specific control to
            show up.
          selector: a raw CSS selector matches at least one element.

        Each poll is one bounded Runtime.evaluate, not a full snapshot() —
        snapshot() only runs once, after the condition is already true, so
        polling stays cheap even at a short poll_interval.

        Raises a typed NETWORK_TIMEOUT with a retry/re-snapshot hint if the
        condition never becomes true within `timeout`.
        """
        kinds = [
            (name, value) for name, value in (("text", text), ("ref", ref),
                                                ("selector", selector))
            if value is not None
        ]
        if len(kinds) != 1:
            raise ValueError(
                "wait_for(): pass exactly one of text=, ref=, or selector="
            )
        kind, needle = kinds[0]
        js = {"text": _WAIT_TEXT_JS, "ref": _WAIT_ELEMENT_JS, "selector": _WAIT_SELECTOR_JS}[kind]
        await self._ensure_initialized()
        t0 = time.monotonic()
        deadline = time.monotonic() + timeout
        while True:
            ok = await self._eval(f"({js})({json.dumps(needle)})")
            if ok:
                break
            if time.monotonic() >= deadline:
                self._trace.add(TraceEntry(
                    timestamp=time.time(),
                    action="wait_for",
                    input={"kind": kind, "value": needle, "timeout": timeout},
                    output={"ok": False},
                    tokens_consumed=0,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                ))
                raise GripError(BrowserError(
                    type=ErrorType.NETWORK_TIMEOUT,
                    message=(
                        f"wait_for({kind}={needle!r}) timed out after "
                        f"{timeout}s — the condition never became true. "
                        "Re-snapshot to see the page's current state, or "
                        "retry wait_for() with a longer timeout."
                    ),
                    confidence=0.6,
                    recovery=[RecoveryAction.RETRY, RecoveryAction.RE_SNAPSHOT],
                ))
            await asyncio.sleep(poll_interval)
        await self.snapshot()
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="wait_for",
            input={"kind": kind, "value": needle, "timeout": timeout},
            output={"ok": True},
            tokens_consumed=0,
            duration_ms=int((time.monotonic() - t0) * 1000),
        ))

    async def upload(self, description: str, *paths: str | Path) -> None:
        """Set one or more local files on a `<input type=file>` matched by
        fuzzy description (label text, aria-label, name, or id).

        Multiple paths set multiple files on the same input in one call —
        DOM.setFileInputFiles takes a list, so there is no per-file round trip.
        A single-file input just keeps whatever the browser allows of it.

        Falls back to `_upload_via_file_chooser()` when no `<input type=file>`
        is addressable this way — a drop-zone/"Browse" control that only
        creates or opens its file input once clicked.
        """
        self._assert_not_safe("upload")
        if not paths:
            raise ValueError("upload() requires at least one file path")
        resolved: list[str] = []
        for p in paths:
            pp = Path(p)
            # Local stat calls, not network I/O — flake8-async's blanket
            # "no Path methods in an async def" rule is aimed at accidental
            # blocking disk/network access, which a single stat is not.
            if not pp.is_file():  # noqa: ASYNC240
                raise FileNotFoundError(f"upload(): file not found: {pp}")
            resolved.append(str(pp.resolve()))  # noqa: ASYNC240

        await self._ensure_initialized()
        t0 = time.monotonic()
        raw = await self._eval(_FIND_FILE_INPUTS_JS)
        candidates = json.loads(raw) if isinstance(raw, str) else (raw or [])
        # _FIND_FILE_INPUTS_JS's stamp() reuses a data-grip-h attribute a page
        # already had rather than overwriting it — see _VALID_HANDLE_RE — so a
        # candidate whose handle isn't one gripStamp/this file would ever
        # issue is dropped before its handle reaches _RESOLVE_FILE_INPUT_JS.
        candidates = [c for c in candidates if _is_trusted_handle(c.get("handle", ""))]
        desc_lower = description.lower()
        match = None
        for c in candidates:
            haystack = " ".join(filter(None, [
                c.get("label", ""), c.get("aria", ""), c.get("name", ""), c.get("id", ""),
            ])).lower()
            if desc_lower in haystack:
                match = c
                break
        if match is None:
            await self._upload_via_file_chooser(description, resolved, t0)
            return

        # DOM.setFileInputFiles needs an objectId, not the JSON description
        # candidates were matched against above — a second, targeted
        # Runtime.evaluate gets one for exactly the element that matched.
        await self._engine.send("DOM.enable")
        resolve_js = f"({_RESOLVE_FILE_INPUT_JS})({json.dumps(match['handle'])})"
        obj_result = await self._engine.send(
            "Runtime.evaluate", {"expression": resolve_js, "returnByValue": False}
        )
        object_id = obj_result.get("result", {}).get("objectId")
        if not object_id:
            raise GripError(BrowserError(
                type=ErrorType.ELEMENT_STALE,
                message=(
                    f"File input for {description!r} disappeared between being "
                    "matched and being resolved. Retry."
                ),
                confidence=1.0,
                recovery=[RecoveryAction.RE_SNAPSHOT],
            ))
        await self._engine.send(
            "DOM.setFileInputFiles", {"files": resolved, "objectId": object_id}
        )
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="upload",
            input={"description": description, "files": resolved},
            output={"handle": match["handle"]},
            tokens_consumed=0,
            duration_ms=int((time.monotonic() - t0) * 1000),
        ))

    async def _upload_via_file_chooser(
        self, description: str, resolved: list[str], t0: float
    ) -> None:
        """Fallback for upload() when no `<input type=file>` is already
        addressable by label/aria/name/id — a drop-zone/"Browse" control that
        creates or opens its file input only once clicked.
        Page.setInterceptFileChooserDialog pauses the native chooser Chrome
        would otherwise try to show (impossible headless) and hands back the
        clicked input's backendNodeId directly, so this needs no separate
        resolve-to-objectId step the way the direct path above does.

        Dispatches a real, trusted pointer click (click_at(), the same
        primitive click_at()/click(human=True) use) rather than click()'s own
        default el.click() — verified against real Chrome that
        Page.fileChooserOpened only fires for a trusted click, headless or
        not; an untrusted JS .click() (even on the file input itself) never
        triggers it.
        """
        if not self._current_snapshot:
            await self.snapshot()
        el = self._find_element(description)
        if el is None:
            raise GripError(self._classifier.classify_semantic_miss(description))
        probe = await self._eval(
            f"({RESOLVE_POINT_JS})"
            f"({json.dumps(el.handle)}, {json.dumps(el.tag)}, {json.dumps(el.text)})"
        )
        outcome = probe or {}
        if not outcome.get("ok"):
            self._raise_for_action(outcome, description)
            return

        await self._ensure_page_domain()
        await self._engine.send("DOM.enable")
        chooser: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

        def on_chooser(params: dict[str, Any]) -> None:
            if not chooser.done():
                chooser.set_result(params)

        self._engine.on("Page.fileChooserOpened", on_chooser)
        try:
            await self._engine.send(
                "Page.setInterceptFileChooserDialog", {"enabled": True}
            )
            await self.click_at(int(outcome["x"]), int(outcome["y"]), human=False)
            try:
                async with asyncio.timeout(5.0):
                    params = await chooser
            except TimeoutError as e:
                raise GripError(BrowserError(
                    type=ErrorType.ELEMENT_STALE,
                    message=(
                        f"Clicking {description!r} did not open a file "
                        "chooser within 5s. It may not be a file upload "
                        "control."
                    ),
                    confidence=0.7,
                    recovery=[RecoveryAction.RE_SNAPSHOT],
                )) from e
            backend_node_id = params.get("backendNodeId")
            if not backend_node_id:
                raise GripError(BrowserError(
                    type=ErrorType.ELEMENT_STALE,
                    message=(
                        f"File chooser opened by {description!r} carried no "
                        "backendNodeId to set files on."
                    ),
                    confidence=0.8,
                    recovery=[RecoveryAction.RETRY],
                ))
            await self._engine.send(
                "DOM.setFileInputFiles",
                {"files": resolved, "backendNodeId": backend_node_id},
            )
        finally:
            self._engine.off("Page.fileChooserOpened", on_chooser)
            with contextlib.suppress(Exception):
                await self._engine.send(
                    "Page.setInterceptFileChooserDialog", {"enabled": False}
                )
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="upload",
            input={"description": description, "files": resolved, "via": "file_chooser"},
            output={},
            tokens_consumed=0,
            duration_ms=int((time.monotonic() - t0) * 1000),
        ))

    async def enable_downloads(self, directory: str | Path) -> Path:
        """Save this page's downloads under `directory` instead of showing
        Chrome's save dialog, and start tracking completions for
        wait_for_download(). Returns the resolved directory.

        Uses Browser.setDownloadBehavior rather than the older Page-scoped
        variant: only Browser.downloadProgress's "completed" event carries the
        real on-disk filePath (Chrome renames on a same-name collision), so it
        is the only source that does not have to guess where the file landed.
        Empirically, this works fine issued over a page-target connection —
        no browser-level session is needed.

        WARNING — Browser.setDownloadBehavior is browser-wide, not scoped to
        this Page/tab, despite being called from here: one Page enabling
        downloads redirects every tab's downloads to `directory`, and a
        second Page calling this with a different directory moves the
        browser-wide target again for every tab, this one included. There is
        no per-tab download directory in CDP. Callers managing multiple pages
        that download concurrently need to be aware they share one
        destination, last-caller-wins. _on_download_progress() below also
        only trusts a completed download's filePath if it resolves under
        this Page's own configured directory — the browser can report a
        completion for a download a different Page/tab actually started, and
        a caller here should not receive a path outside what it configured.
        """
        self._assert_not_safe("enable_downloads")
        path = Path(directory)
        # mode=0o700: a new download dir should not be world-readable/listable
        # (umask would otherwise leave it at the process default). exist_ok=True
        # means an already-existing dir keeps its own permissions — that's fine,
        # this only tightens dirs it creates itself.
        path.mkdir(mode=0o700, parents=True, exist_ok=True)  # noqa: ASYNC240 — local stat/mkdir, not I/O we need off-thread
        path = path.resolve()  # noqa: ASYNC240
        await self._ensure_initialized()
        await self._engine.send("Page.enable")
        # Listener must be registered before the enabling send below, not
        # after: a download that completes while Browser.setDownloadBehavior
        # is in flight would otherwise fire downloadProgress into a void and
        # wait_for_download() would time out despite the file being on disk.
        # Mirrors _ensure_fetch_interception()/_ensure_popup_blocking() above.
        if not self._download_events_armed:
            self._download_events_armed = True
            self._download_queue = asyncio.Queue()
            self._engine.on("Browser.downloadProgress", self._on_download_progress)
        # Same "before, not after" reasoning as the listener above:
        # _on_download_progress checks completions against _download_dir (see
        # _is_under_download_dir), so it has to be set before
        # Browser.setDownloadBehavior can possibly complete — not after —
        # or a download finishing while that send is still in flight would
        # find _download_dir still None and get dropped as untrusted.
        self._download_dir = path
        await self._engine.send(
            "Browser.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": str(path), "eventsEnabled": True},
        )
        return path

    def _is_under_download_dir(self, file_path: str) -> bool:
        """True only if `file_path` resolves under this Page's configured
        download directory. Browser.setDownloadBehavior is browser-wide (see
        enable_downloads()'s docstring), so the filePath Chrome reports here
        can belong to a download a different Page/tab started under its own
        directory — trusted verbatim, that path would otherwise be handed
        straight back to this Page's caller as if it were the file this Page
        asked for."""
        if self._download_dir is None:
            return False
        try:
            return Path(file_path).resolve().is_relative_to(self._download_dir)
        except (OSError, ValueError):
            return False

    def _on_download_progress(self, params: dict[str, Any]) -> None:
        if self._download_queue is None:
            return
        state = params.get("state")
        if state == "completed":
            file_path = params.get("filePath")
            if file_path and self._is_under_download_dir(file_path):
                self._download_queue.put_nowait(Path(file_path))
            elif file_path:
                logger.warning(
                    "wait_for_download(): ignoring a completed download at %r — "
                    "outside this Page's configured download directory %r. "
                    "Browser.setDownloadBehavior is browser-wide (see "
                    "enable_downloads()), so this is likely a different "
                    "Page/tab's download, not this one's.",
                    file_path, str(self._download_dir),
                )
        elif state == "canceled":
            # Queued as None rather than dropped: a canceled download should
            # not read to a waiting caller as indistinguishable from one that
            # simply hasn't finished yet.
            self._download_queue.put_nowait(None)

    async def wait_for_download(self, timeout: float = 30.0) -> Path:
        """Block until the next download this page starts finishes, and
        return the local path it was saved to. Requires enable_downloads()
        first."""
        if self._download_queue is None:
            raise RuntimeError(
                "wait_for_download() called before enable_downloads()"
            )
        try:
            item = await asyncio.wait_for(self._download_queue.get(), timeout=timeout)
        except TimeoutError as e:
            raise GripError(BrowserError(
                type=ErrorType.NETWORK_TIMEOUT,
                message=f"No download completed within {timeout}s.",
                confidence=1.0,
                recovery=[RecoveryAction.RETRY],
            )) from e
        if item is None:
            raise GripError(BrowserError(
                type=ErrorType.NETWORK_TIMEOUT,
                message="Download was canceled before it finished.",
                confidence=1.0,
                recovery=[],
            ))
        return item

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

    # select()'s outcome shape shares "stale handle" with click()/type() but
    # has two failure modes neither of theirs does (wrong element kind, no
    # matching option), so it gets its own mapping rather than overloading
    # _raise_for_action's reason switch with select-only branches.
    def _raise_for_select(
        self, outcome: dict[str, Any], description: str, value: str
    ) -> None:
        if outcome.get("ok"):
            return
        reason = outcome.get("reason", "")
        if reason == "not_a_select":
            raise GripError(
                self._classifier.classify_not_a_select(description, outcome.get("tag", ""))
            )
        if reason == "no_such_option":
            raise GripError(
                self._classifier.classify_invalid_option(
                    description, value, outcome.get("options", [])
                )
            )
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

    async def press(self, key: str, modifiers: list[str] | None = None) -> None:
        """Dispatch a key press: `key` is a single character ("a", "$") or a
        named key ("Enter", "Tab", "ArrowDown", ...). `modifiers` is any of
        "alt"/"ctrl"/"shift"/"meta" (case-insensitive).

        Sending only `key` (the old behaviour) produced no `code`/
        `windowsVirtualKeyCode`/`text` — real pages gate keydown handlers on
        `event.code`, and a character key with no `text` typed nothing at
        all, so a keyboard-only widget (an autocomplete, a shortcut, a
        canvas-based editor with no real <input>) was unreachable through
        press(). Named keys get a real code/VK pair (see _NAMED_KEYS); a
        single printable character gets a keyDown/char/keyUp triplet so both
        a keydown-gated listener and the field's own value update fire, the
        same as a real keystroke. An unrecognized multi-character name (e.g.
        "F5") still falls back to key-only rather than raising — some
        model-supplied names should still reach the page even without a
        code/VK mapping this file doesn't have.
        """
        self._assert_not_safe("press")
        bits = _modifiers_bitmask(modifiers)
        if key in _NAMED_KEYS:
            code, vk = _NAMED_KEYS[key]
            base: dict[str, Any] = {
                "key": key, "code": code,
                "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
                "modifiers": bits,
            }
            await self._engine.send("Input.dispatchKeyEvent", {**base, "type": "keyDown"})
            await self._engine.send("Input.dispatchKeyEvent", {**base, "type": "keyUp"})
            return
        if len(key) == 1:
            vk = ord(key.upper()) if key.isalnum() else 0
            base = {"key": key, "windowsVirtualKeyCode": vk, "modifiers": bits}
            await self._engine.send("Input.dispatchKeyEvent", {**base, "type": "keyDown"})
            await self._engine.send(
                "Input.dispatchKeyEvent", {**base, "type": "char", "text": key}
            )
            await self._engine.send("Input.dispatchKeyEvent", {**base, "type": "keyUp"})
            return
        await self._engine.send(
            "Input.dispatchKeyEvent", {"type": "keyDown", "key": key, "modifiers": bits}
        )
        await self._engine.send(
            "Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "modifiers": bits}
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

    async def hover(self, description: str, *, human: bool = False) -> None:
        """Move the pointer over an element without clicking it — the
        primitive hover-only menus/tooltips need, since click()'s default JS
        path (el.click()) fires no pointer events at all and hover-revealed
        content never has a chance to appear.

        Reuses the same probe click(human=True) uses to turn `description`
        into real viewport coordinates: RESOLVE_POINT_JS re-resolves the
        handle first, so a stale element raises instead of hovering whatever
        now occupies that spot. `human=True` travels there along the same
        curved, eased path click_at() uses; the default is a single instant
        move, since most hover targets don't need to survive a bot-motion
        check and every intermediate step is a real wall-clock sleep
        (move_delay()) an ordinary "open this menu" call shouldn't pay.

        Does not re-snapshot afterward, matching click()/type()/select() —
        the caller's next snapshot()/payload() picks up whatever the hover
        revealed.
        """
        self._assert_not_safe("hover")
        if not self._current_snapshot:
            await self.snapshot()
        t0 = time.monotonic()
        el = self._find_element(description)
        if el is None:
            err = self._classifier.classify_semantic_miss(description)
            raise GripError(err)
        probe = await self._eval(
            f"({RESOLVE_POINT_JS})"
            f"({json.dumps(el.handle)}, {json.dumps(el.tag)}, {json.dumps(el.text)})"
        )
        outcome = probe or {}
        if outcome.get("ok"):
            x, y = int(outcome["x"]), int(outcome["y"])
            if human:
                await self._move_pointer((self._pointer_x, self._pointer_y), (x, y))
            else:
                await self._mouse("mouseMoved", x, y)
            self._pointer_x, self._pointer_y = x, y
            # A hover-revealed menu/tooltip is itself a DOM change — see
            # click()'s matching _settle() call for why this waits rather
            # than letting the caller's next snapshot() race it.
            await self._settle()
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="hover",
            input={"description": description, "handle": el.handle, "human": human},
            output={"success": bool(outcome.get("ok")),
                    "reason": outcome.get("reason", "")},
            tokens_consumed=0,
            duration_ms=int((time.monotonic() - t0) * 1000),
        ))
        self._raise_for_action(outcome, description)

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

    def _raise_if_stale_ref(self, description: str) -> None:
        # Only reached once every exact/fuzzy match has already failed. A
        # description that looks like a ref this registry once issued but
        # names nothing live is a *different* failure than "no such element":
        # the caller is holding a ref from a document (or a since-evicted
        # element) that no longer exists, and re-snapshotting is the only fix
        # — retrying the same ref text again cannot succeed.
        if self._refs.is_stale(description):
            raise GripError(self._classifier.classify_stale_ref(description))

    # Shared ladder for click()/type()/select() target resolution, mirroring
    # _SELECT_OPTION_JS's own precedence (exact visible text, then a unique
    # substring, never resolving a non-unique match silently):
    #   1. exact text match (case-insensitive) — wins outright, even over a
    #      substring match elsewhere, so click("Save") always hits the button
    #      literally labeled "Save" and never "Save draft".
    #   2. exact ref match (e.g. "e5") — unambiguous by construction, since
    #      RefRegistry never assigns the same ref to two live elements.
    #   3. a *unique* substring across text/placeholder/role — a description
    #      matching more than one candidate is reported as AMBIGUOUS_TARGET
    #      rather than resolved to whichever came first in document order.
    # `candidates` is already filtered to the right kind of element (inputs
    # for _find_input, <select> for _find_select) — an exact ref that names
    # a live element of the WRONG kind is not found here, same as before.
    def _resolve_target(self, description: str, candidates: list[Element]) -> Element | None:
        desc_lower = description.lower()
        exact_text = [el for el in candidates if el.text.lower() == desc_lower]
        if len(exact_text) == 1:
            return exact_text[0]
        if len(exact_text) > 1:
            raise GripError(self._classifier.classify_ambiguous_target(
                description, [(el.ref, el.text or el.role) for el in exact_text]
            ))
        for el in candidates:
            if el.ref == description:
                return el
        substr = [
            el for el in candidates
            if desc_lower in el.text.lower()
            or desc_lower in (el.placeholder or "").lower()
            or desc_lower in el.role.lower()
        ]
        if len(substr) > 1:
            raise GripError(self._classifier.classify_ambiguous_target(
                description, [(el.ref, el.text or el.role) for el in substr]
            ))
        if substr:
            return substr[0]
        self._raise_if_stale_ref(description)
        return None

    def _find_element(self, description: str) -> Element | None:
        if not self._current_snapshot:
            return None
        return self._resolve_target(description, self._current_snapshot.elements)

    def _find_input(self, description: str) -> Element | None:
        if not self._current_snapshot:
            return None
        candidates = [
            el for el in self._current_snapshot.elements
            if el.tag in ("input", "textarea") or el.role == "textbox"
        ]
        return self._resolve_target(description, candidates)

    def _find_select(self, description: str) -> Element | None:
        if not self._current_snapshot:
            return None
        # Filtered to <select> the same way _find_input filters to
        # inputs/textareas — an unfiltered match (bare _find_element) can
        # land on a button/link sharing the same label ("Sort") before it
        # ever reaches the actual dropdown.
        candidates = [el for el in self._current_snapshot.elements if el.tag == "select"]
        return self._resolve_target(description, candidates)

    def _find_combobox(self, description: str) -> Element | None:
        if not self._current_snapshot:
            return None
        candidates = [el for el in self._current_snapshot.elements if el.is_combobox]
        return self._resolve_target(description, candidates)

    def _find_combobox_option(self, value: str) -> Element | None:
        if not self._current_snapshot:
            return None
        # role="option" is the ARIA combobox pattern's own answer to "which
        # of these newly-rendered elements is a choice" — preferred over a
        # bare text scan so a page's surrounding prose can't accidentally
        # outrank the actual option. Not every custom widget uses it though,
        # so an empty role="option" set falls back to every element, the
        # same ladder click()'s own _find_element uses.
        candidates = [el for el in self._current_snapshot.elements if el.role == "option"]
        if not candidates:
            candidates = self._current_snapshot.elements
        return self._resolve_target(value, candidates)

    async def _select_combobox(self, el: Element, value: str, t0: float) -> None:
        """select()'s fallback for a non-native combobox (see _find_combobox):
        open it if it isn't already expanded, re-snapshot to discover
        whatever options that click rendered (a custom widget typically
        creates its option list on demand, so the pre-click snapshot never
        has it), then click the one matching `value`.
        """
        if not el.combobox_expanded:
            await self.click(el.ref)
        await self.snapshot()
        option = self._find_combobox_option(value)
        if option is None:
            raise GripError(self._classifier.classify_invalid_option(
                el.text or el.ref, value,
                [o.text for o in self._current_snapshot.elements if o.role == "option"]
                if self._current_snapshot else [],
            ))
        await self.click(option.ref)
        self._trace.add(TraceEntry(
            timestamp=time.time(),
            action="select",
            input={
                "description": el.text or el.ref, "value": value,
                "handle": el.handle, "via": "combobox",
            },
            output={"success": True, "reason": ""},
            tokens_consumed=0,
            duration_ms=int((time.monotonic() - t0) * 1000),
        ))

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
                # gripElementState (grip/cdp/shadow.py) — see RawElement's
                # docstring for why value needs no redaction here.
                disabled=d.get("disabled", False),
                required=d.get("required", False),
                checked=d.get("checked"),
                selected=d.get("selected"),
                value=d.get("value"),
                # See RawElement's own docstring — mirrored onto Element in
                # grip/compression/summarizer.py.
                canvas_width=d.get("canvasWidth"),
                canvas_height=d.get("canvasHeight"),
                is_combobox=d.get("isCombobox", False),
                combobox_expanded=d.get("comboboxExpanded"),
                combobox_options=d.get("comboboxOptions"),
                closed_shadow_unreadable=d.get("closedShadowUnreadable", False),
            )
            for d in raw_data
            # See _VALID_HANDLE_RE — an element whose handle isn't one gripStamp
            # would issue is dropped rather than made addressable.
            if _is_trusted_handle(d.get("handle", ""))
        ]

    async def _resolve_probe_object_ids(self, handles: list[str]) -> dict[str, str]:
        """Resolves every stamped handle to its live DOM object id in one
        Runtime.evaluate (an array of elements) plus one Runtime.getProperties
        call, rather than one Runtime.evaluate per handle — the 2 (not 2N)
        round trips this pass is bounded to before the per-node listener
        checks, which are unavoidably one CDP call each."""
        expr = (
            "(function(hs){ return hs.map(function(h){"
            " return document.querySelector('[data-grip-h=\"' + CSS.escape(h) + '\"]');"
            " }); })"
            f"({json.dumps(handles)})"
        )
        result = await self._engine.send(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": False, "objectGroup": _PROBE_OBJECT_GROUP},
        )
        array_object_id = result.get("result", {}).get("objectId")
        if not array_object_id:
            return {}
        props = await self._engine.send(
            "Runtime.getProperties", {"objectId": array_object_id, "ownProperties": True}
        )
        out: dict[str, str] = {}
        for prop in props.get("result", []):
            name = prop.get("name", "")
            if not name.isdigit():
                continue
            idx = int(name)
            if idx >= len(handles):
                continue
            value = prop.get("value", {})
            obj_id = value.get("objectId")
            # A handle DISCOVER's own pass stamped a moment earlier but that has
            # since been removed (page re-rendered mid-snapshot) resolves to
            # null here — skipped rather than probed.
            if obj_id and value.get("subtype") != "null":
                out[handles[idx]] = obj_id
        return out

    async def _has_click_listener_for(self, object_id: str) -> bool:
        try:
            result = await self._engine.send(
                "DOMDebugger.getEventListeners", {"objectId": object_id}
            )
        except Exception:
            return False
        return _has_click_listener(result.get("listeners", []))

    async def _discover_probe_elements(self) -> list[RawElement]:
        """Bounded second pass (grip/cdp/shadow.py:PROBE_CLICKABLE_JS + CDP
        DOMDebugger.getEventListeners) for elements that are clickable only
        via a JS listener — no role, no tabindex, no native semantics.
        Never allowed to fail a snapshot: any error anywhere in this path
        degrades to "no probe elements found" rather than raising, since this
        is a heuristic add-on to the semantic DISCOVER path snapshot()
        already depends on."""
        try:
            async with asyncio.timeout(_PROBE_TIMEOUT_S):
                return await self._discover_probe_elements_inner()
        except Exception:
            return []

    async def _discover_probe_elements_inner(self) -> list[RawElement]:
        result = await self._engine.send(
            "Runtime.evaluate", {"expression": PROBE_CLICKABLE_JS, "returnByValue": True}
        )
        raw = result.get("result", {}).get("value")
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not raw:
            return []
        # See _VALID_HANDLE_RE: PROBE_CLICKABLE_JS stamps handles the same way
        # DISCOVER does, so the same page-authored-attribute-reuse risk
        # applies here — an untrusted handle is dropped before it reaches
        # _resolve_probe_object_ids's querySelector.
        handles = [
            d.get("handle", "") for d in raw
            if d.get("handle") and _is_trusted_handle(d.get("handle", ""))
        ]
        if not handles:
            return []
        try:
            object_ids = await self._resolve_probe_object_ids(handles)
            if not object_ids:
                return []
            # One CDP call per node is unavoidable (DOMDebugger.getEventListeners
            # is per-object), but the N calls run concurrently rather than
            # sequentially, so wall time tracks the slowest single call, not N
            # times a single call's latency.
            handles_checked = list(object_ids.keys())
            checks = await asyncio.gather(
                *(self._has_click_listener_for(object_ids[h]) for h in handles_checked),
                return_exceptions=True,
            )
            clickable_handles = {
                h for h, ok in zip(handles_checked, checks, strict=True) if ok is True
            }
        finally:
            # Shielded: this whole method runs inside _discover_probe_elements's
            # asyncio.timeout(_PROBE_TIMEOUT_S). On a probe timeout, the
            # CancelledError that timeout injects lands exactly here (the
            # `finally` of the try this code is already inside) and would
            # otherwise cancel this send() before it reaches the browser —
            # skipping the release and leaking up to
            # GRIP_MAX_LISTENER_PROBE_NODES DOM objects in the renderer per
            # snapshot that timed out. shield() lets this one call finish (or
            # fail on its own) instead of dying with the coroutine that's
            # already being torn down around it.
            with contextlib.suppress(Exception):
                await asyncio.shield(self._engine.send(
                    "Runtime.releaseObjectGroup", {"objectGroup": _PROBE_OBJECT_GROUP}
                ))
        out = []
        for d in raw:
            handle = d.get("handle", "")
            if handle not in clickable_handles:
                continue
            out.append(RawElement(
                tag=d.get("tag", ""),
                role=d.get("role") or d.get("tag", ""),
                text=d.get("text", ""),
                placeholder=None,
                in_shadow_dom=d.get("inShadowDom", False),
                cx=d.get("cx", 0),
                cy=d.get("cy", 0),
                computed_display="block",
                computed_visibility="visible",
                computed_opacity="1",
                aria_hidden=False,
                width=1,
                height=1,
                href=None,
                handle=handle,
                # PROBE_CLICKABLE_JS (grip/cdp/shadow.py) never collects
                # gripElementState — these probe-only elements have no role,
                # no tabindex, no native semantics to begin with, so there is
                # no interaction state to report. Mapped explicitly (rather
                # than left to RawElement's own defaults) so this is a
                # documented "unknown", not a spot that looks like it was
                # forgotten.
                disabled=d.get("disabled", False),
                required=d.get("required", False),
                checked=d.get("checked"),
                selected=d.get("selected"),
                value=d.get("value"),
            ))
        return out

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
