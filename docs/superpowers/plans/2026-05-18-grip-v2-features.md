# grip v2 Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 7 independent enhancements to grip v0.1.0 — stable element refs, iframe filtering, page-state detection, search macros, read-only safe mode, proxy support, and session persistence.

**Architecture:** Each task is self-contained; they can be implemented in any order. Tasks 1–3 improve the snapshot/element model. Tasks 4–5 add new Browser capabilities. Tasks 6–7 add infrastructure features (proxy, cookies).

**Tech Stack:** Python 3.11+, asyncio, Chrome DevTools Protocol (CDP), websockets, hatchling

---

## File map

| File | Change |
|---|---|
| `grip/cdp/shadow.py` | Task 1 — iframe filtering in JS |
| `grip/compression/summarizer.py` | Task 2 — `page_error` on PageSnapshot; Task 3 — `ref` on Element |
| `grip/compression/refs.py` | Task 3 — new RefRegistry |
| `grip/page.py` | Tasks 2, 3 — wire detect + refs |
| `grip/errors/types.py` | Tasks 2, 5 — import in tests; Task 5 — SAFE_MODE_VIOLATION |
| `grip/browser.py` | Tasks 4, 5, 6, 7 — macros, safe, proxy, session |
| `grip/cdp/launcher.py` | Task 6 — proxy flag |
| `grip/__init__.py` | Task 3, 5 — export new symbols |
| `tests/unit/test_shadow.py` | Task 1 |
| `tests/unit/test_snapshot_page_error.py` | Task 2 |
| `tests/unit/test_refs.py` | Task 3 |
| `tests/unit/test_macros.py` | Task 4 |
| `tests/unit/test_safe_mode.py` | Task 5 |
| `tests/unit/test_error_types.py` | Task 5 — update enum check |
| `tests/unit/test_proxy.py` | Task 6 |
| `tests/unit/test_session.py` | Task 7 |

---

## Task 1: Iframe noise filtering

Skip known analytics/tracking iframes in `DISCOVER_ELEMENTS_JS` so they don't clutter the element list.

**Files:**
- Modify: `grip/cdp/shadow.py`
- Test: `tests/unit/test_shadow.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_shadow.py`:

```python
def test_discover_js_skips_tracking_iframe():
    assert "googletagmanager" in DISCOVER_ELEMENTS_JS
    assert "isTracking" in DISCOVER_ELEMENTS_JS
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python3 -m pytest tests/unit/test_shadow.py::test_discover_js_skips_tracking_iframe -v
```
Expected: FAIL — `AssertionError: assert 'googletagmanager' in ...`

- [ ] **Step 3: Add iframe filtering to DISCOVER_ELEMENTS_JS**

In `grip/cdp/shadow.py`, inside the `while (node)` loop of `collectElements`, add this block immediately after the `const tag = el.tagName.toLowerCase();` line:

```javascript
      if (tag === 'iframe') {
        const src = el.getAttribute('src') || el.getAttribute('data-src') || '';
        const isTracking = [
          'googletagmanager', 'google-analytics', 'facebook.net', 'hotjar',
          'sentry', 'recaptcha', 'doubleclick', 'analytics', 'pixel', 'tracking'
        ].some(p => src.includes(p));
        if (isTracking) { node = walker.nextNode(); continue; }
      }
```

The full updated `collectElements` function becomes:

```javascript
  function collectElements(root, inShadow) {
    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_ELEMENT,
      null
    );
    let node = walker.currentNode;
    while (node) {
      const el = node;
      if (!el.tagName) { node = walker.nextNode(); continue; }
      const tag = el.tagName.toLowerCase();

      if (tag === 'iframe') {
        const src = el.getAttribute('src') || el.getAttribute('data-src') || '';
        const isTracking = [
          'googletagmanager', 'google-analytics', 'facebook.net', 'hotjar',
          'sentry', 'recaptcha', 'doubleclick', 'analytics', 'pixel', 'tracking'
        ].some(p => src.includes(p));
        if (isTracking) { node = walker.nextNode(); continue; }
      }

      const role = el.getAttribute('role') || el.getAttribute('aria-role') || '';
      const ariaHidden = el.getAttribute('aria-hidden') === 'true';
      const style = window.getComputedStyle(el);
      const hidden = (
        style.display === 'none' ||
        style.visibility === 'hidden' ||
        parseFloat(style.opacity) === 0 ||
        ariaHidden ||
        el.offsetWidth === 0 ||
        el.offsetHeight === 0
      );

      if (!hidden && (INTERACTIVE_TAGS.has(tag) || INTERACTIVE_ROLES.has(role))) {
        const rect = el.getBoundingClientRect();
        results.push({
          index: idx++,
          tag: tag,
          role: role || tag,
          text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 120),
          placeholder: el.getAttribute('placeholder') || null,
          inShadowDom: inShadow,
          cx: Math.round(rect.left + rect.width / 2),
          cy: Math.round(rect.top + rect.height / 2),
        });
      }

      if (el.shadowRoot) {
        collectElements(el.shadowRoot, true);
      }
      node = walker.nextNode();
    }
  }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/python3 -m pytest tests/unit/test_shadow.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add grip/cdp/shadow.py tests/unit/test_shadow.py
git commit -m "feat: skip tracking iframes in element discovery"
```

---

## Task 2: Wire page-state detection into snapshot()

Surface bot blocks, captchas, and auth walls as `snapshot.page_error` so agents can branch without catching exceptions.

**Files:**
- Modify: `grip/compression/summarizer.py` (add `page_error` field to `PageSnapshot`)
- Modify: `grip/page.py` (call classifier after getting title/url)
- Create: `tests/unit/test_snapshot_page_error.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_snapshot_page_error.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from grip.page import Page
from grip.errors.types import ErrorType
from grip.trace import Trace


def _make_page():
    engine = MagicMock()
    engine.send = AsyncMock()
    return Page(engine=engine, trace=Trace())


def test_page_snapshot_has_page_error_field():
    from grip.compression.summarizer import PageSnapshot
    snap = PageSnapshot(
        version=1, url="https://example.com", title="Test",
        elements=[], text_content="hello", tokens_estimated=5,
    )
    assert snap.page_error is None


@pytest.mark.asyncio
async def test_snapshot_detects_bot_block():
    page = _make_page()
    page._engine.send.side_effect = [
        # Runtime.enable
        {},
        # Page.enable
        {},
        # DISCOVER_ELEMENTS_JS
        {"result": {"value": "[]"}},
        # PAGE_TEXT_JS
        {"result": {"value": "Access denied"}},
        # Target.getTargetInfo
        {"targetInfo": {"title": "Access Denied | Cloudflare", "url": "https://example.com/blocked"}},
    ]
    snapshot = await page.snapshot()
    assert snapshot.page_error is not None
    assert snapshot.page_error.type == ErrorType.ANTI_BOT_BLOCK


@pytest.mark.asyncio
async def test_snapshot_page_error_none_on_normal_page():
    page = _make_page()
    page._engine.send.side_effect = [
        {}, {},
        {"result": {"value": "[]"}},
        {"result": {"value": "Hello world"}},
        {"targetInfo": {"title": "Example Domain", "url": "https://example.com"}},
    ]
    snapshot = await page.snapshot()
    assert snapshot.page_error is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python3 -m pytest tests/unit/test_snapshot_page_error.py -v
```
Expected: FAIL — `AttributeError: 'PageSnapshot' object has no attribute 'page_error'`

- [ ] **Step 3: Add `page_error` to PageSnapshot**

In `grip/compression/summarizer.py`, update the `PageSnapshot` dataclass:

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from grip.errors.types import BrowserError

from grip.security.sanitizer import RawElement

# ... (keep existing tiktoken block and _TAG_ABBREV unchanged) ...

@dataclass
class Element:
    index: int
    snapshot_version: int
    tag: str
    role: str
    text: str
    placeholder: str | None
    in_shadow_dom: bool
    cx: int
    cy: int
    ref: str = ""


@dataclass
class PageSnapshot:
    version: int
    url: str
    title: str
    elements: list[Element]
    text_content: str
    tokens_estimated: int
    changed_from_previous: bool = True
    page_error: "BrowserError | None" = None
```

Note: `ref: str = ""` is added to `Element` now — it will be populated in Task 3. Adding it here avoids a second dataclass change.

- [ ] **Step 4: Wire classifier into Page.snapshot()**

In `grip/page.py`, update the `snapshot()` method. After the `title, url = await self._get_page_info()` line, add:

```python
        # Detect bot blocks, captchas, auth walls
        from grip.errors.types import ErrorType as ET
        page_error = None
        _detected = self._classifier.classify_page_state(title, url, 0)
        if _detected.type in (
            ET.ANTI_BOT_BLOCK, ET.CAPTCHA_REQUIRED,
            ET.RATE_LIMITED, ET.AUTH_REQUIRED,
        ):
            page_error = _detected
```

Then pass `page_error` into the snapshot after building it:

```python
        snapshot = self._summarizer.build(
            version=self._version,
            url=url,
            title=title,
            raw_elements=raw_elements,
            page_text=safe_text,
        )
        snapshot.page_error = page_error
        changed = self._diff.has_changed(snapshot)
```

The full updated `snapshot()` method in `grip/page.py`:

```python
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

        from grip.errors.types import ErrorType as ET
        page_error = None
        _detected = self._classifier.classify_page_state(title, url, 0)
        if _detected.type in (
            ET.ANTI_BOT_BLOCK, ET.CAPTCHA_REQUIRED,
            ET.RATE_LIMITED, ET.AUTH_REQUIRED,
        ):
            page_error = _detected

        scan = self._injector.scan(page_text)
        safe_text = scan.safe_text

        self._version += 1
        snapshot = self._summarizer.build(
            version=self._version,
            url=url,
            title=title,
            raw_elements=raw_elements,
            page_text=safe_text,
        )
        snapshot.page_error = page_error
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
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python3 -m pytest tests/unit/test_snapshot_page_error.py tests/unit/test_summarizer.py -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add grip/compression/summarizer.py grip/page.py tests/unit/test_snapshot_page_error.py
git commit -m "feat: surface page_error on PageSnapshot for bot blocks and auth walls"
```

---

## Task 3: Stable element refs

Assign stable cross-snapshot identifiers (`e1`, `e2`, ...) to elements so LLMs can reference them reliably. Refs persist across re-snapshots of the same page and reset on URL change.

**Files:**
- Create: `grip/compression/refs.py`
- Modify: `grip/page.py` (instantiate RefRegistry, assign refs, reset on URL change, check ref in find methods)
- Modify: `grip/compression/summarizer.py` (use `ref` in format string)
- Create: `tests/unit/test_refs.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_refs.py`:

```python
from grip.compression.refs import RefRegistry


def test_assigns_e1_to_first_element():
    r = RefRegistry()
    ref = r.assign("button", "Buy Now")
    assert ref == "e1"


def test_same_element_gets_same_ref():
    r = RefRegistry()
    r1 = r.assign("button", "Buy Now")
    r2 = r.assign("button", "Buy Now")
    assert r1 == r2 == "e1"


def test_different_elements_get_different_refs():
    r = RefRegistry()
    r1 = r.assign("button", "Buy Now")
    r2 = r.assign("input", "search")
    assert r1 == "e1"
    assert r2 == "e2"


def test_reset_restarts_numbering():
    r = RefRegistry()
    r.assign("button", "Buy Now")
    r.reset()
    ref = r.assign("button", "Submit")
    assert ref == "e1"


def test_reset_clears_existing_mappings():
    r = RefRegistry()
    r.assign("button", "Buy Now")
    r.reset()
    # Same element after reset gets e1 again (new session)
    ref = r.assign("button", "Buy Now")
    assert ref == "e1"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python3 -m pytest tests/unit/test_refs.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'grip.compression.refs'`

- [ ] **Step 3: Create grip/compression/refs.py**

```python
from __future__ import annotations
import hashlib


def _fingerprint(tag: str, text: str) -> str:
    return hashlib.md5(f"{tag}:{text}".encode()).hexdigest()


class RefRegistry:
    def __init__(self) -> None:
        self._fp_to_ref: dict[str, str] = {}
        self._next: int = 1

    def assign(self, tag: str, text: str) -> str:
        fp = _fingerprint(tag, text)
        if fp not in self._fp_to_ref:
            self._fp_to_ref[fp] = f"e{self._next}"
            self._next += 1
        return self._fp_to_ref[fp]

    def reset(self) -> None:
        self._fp_to_ref.clear()
        self._next = 1
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python3 -m pytest tests/unit/test_refs.py -v
```
Expected: 5 PASS

- [ ] **Step 5: Wire RefRegistry into Page**

In `grip/page.py`, add import and instantiation:

```python
from grip.compression.refs import RefRegistry
```

In `Page.__init__()`, add:
```python
        self._refs = RefRegistry()
        self._current_url: str = ""
```

In `Page.snapshot()`, after `title, url = await self._get_page_info()`, add URL-change detection and ref assignment:

```python
        # Reset refs on URL change (navigation)
        if self._current_url and url != self._current_url:
            self._refs.reset()
        self._current_url = url
```

After `snapshot = self._summarizer.build(...)`, add ref assignment:

```python
        for el in snapshot.elements:
            el.ref = self._refs.assign(el.tag, el.text)
```

In `_find_element_index()`, check ref first:

```python
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
```

In `_find_input_index()`, also check ref first:

```python
    def _find_input_index(self, description: str) -> int | None:
        if not self._current_snapshot:
            return None
        # Exact ref match
        for el in self._current_snapshot.elements:
            if el.ref == description and el.tag in ("input", "textarea"):
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
```

- [ ] **Step 6: Update format string to show refs**

In `grip/compression/summarizer.py`, update `_build_format_str()`:

```python
    def _build_format_str(
        self, url: str, title: str, elements: list[Element], text: str
    ) -> str:
        lines = [f"PAGE: {title}", f"URL: {url}"]
        if elements:
            lines.append("INTERACTIVE:")
            for el in elements:
                abbrev = _TAG_ABBREV.get(el.tag, el.tag[:3])
                desc = el.text or el.placeholder or el.role
                ref = el.ref or str(el.index)
                lines.append(f"  [{abbrev}:{ref}] {desc!r}")
        if text:
            lines.append("CONTENT:")
            lines.append(f"  {text[:2000]}")
        return "\n".join(lines)
```

This outputs `[btn:e1] "Buy Now"` instead of `[btn:0] "Buy Now"`.

- [ ] **Step 7: Run full unit suite**

```bash
.venv/bin/python3 -m pytest tests/unit/ -v
```
Expected: all PASS (refs show in format strings, existing tests still pass because they check for content not exact format)

- [ ] **Step 8: Commit**

```bash
git add grip/compression/refs.py grip/compression/summarizer.py grip/page.py tests/unit/test_refs.py
git commit -m "feat: stable element refs (e1/e2/...) — reset on navigation"
```

---

## Task 4: Search macros

`browser.open("@google_search", query="blue sneakers")` expands to `https://www.google.com/search?q=blue+sneakers`.

**Files:**
- Modify: `grip/browser.py`
- Create: `tests/unit/test_macros.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_macros.py`:

```python
import pytest
from grip.browser import _expand_macro


def test_google_search_macro():
    url = _expand_macro("@google_search", query="blue sneakers")
    assert url == "https://www.google.com/search?q=blue+sneakers"


def test_youtube_search_macro():
    url = _expand_macro("@youtube_search", query="python tutorial")
    assert url == "https://www.youtube.com/results?search_query=python+tutorial"


def test_amazon_search_macro():
    url = _expand_macro("@amazon_search", query="mechanical keyboard")
    assert url == "https://www.amazon.com/s?k=mechanical+keyboard"


def test_non_macro_url_passthrough():
    url = _expand_macro("https://example.com")
    assert url == "https://example.com"


def test_unknown_macro_raises():
    with pytest.raises(ValueError, match="Unknown macro"):
        _expand_macro("@nonexistent", query="test")


def test_macro_encodes_special_chars():
    url = _expand_macro("@google_search", query="C++ programming")
    assert "C%2B%2B" in url or "C++programming" not in url
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python3 -m pytest tests/unit/test_macros.py -v
```
Expected: FAIL — `ImportError: cannot import name '_expand_macro' from 'grip.browser'`

- [ ] **Step 3: Add macros to grip/browser.py**

Add at the top of `grip/browser.py`, after imports:

```python
import urllib.parse

_MACROS: dict[str, str] = {
    "@google_search":    "https://www.google.com/search?q={query}",
    "@youtube_search":   "https://www.youtube.com/results?search_query={query}",
    "@amazon_search":    "https://www.amazon.com/s?k={query}",
    "@github_search":    "https://github.com/search?q={query}",
    "@reddit_search":    "https://www.reddit.com/search/?q={query}",
    "@wikipedia_search": "https://en.wikipedia.org/wiki/Special:Search?search={query}",
    "@twitter_search":   "https://twitter.com/search?q={query}",
    "@yelp_search":      "https://www.yelp.com/search?find_desc={query}",
}


def _expand_macro(url: str, **kwargs: str) -> str:
    if not url.startswith("@"):
        return url
    template = _MACROS.get(url)
    if not template:
        raise ValueError(f"Unknown macro: {url!r}. Available: {sorted(_MACROS)}")
    query = urllib.parse.quote_plus(kwargs.get("query", ""))
    return template.format(query=query)
```

Update `Browser.open()` signature and first line:

```python
    async def open(self, url: str, **kwargs: str) -> Page:
        if not self._engine:
            self._launcher = ChromeLauncher()
            port = self._launcher.launch(headless=self._headless)
            ws_url = await fetch_tab_ws_url(port)
            self._engine = CDPEngine()
            await self._engine.connect(ws_url)

        url = _expand_macro(url, **kwargs)

        if not url.startswith(("http", "about:", "data:", "file:", "blob:")):
            url = "https://" + url
        ...  # rest unchanged
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python3 -m pytest tests/unit/test_macros.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add grip/browser.py tests/unit/test_macros.py
git commit -m "feat: search macros — @google_search, @youtube_search, @amazon_search (+5)"
```

---

## Task 5: Read-only safe mode

`Browser(safe=True)` raises `GripError(SAFE_MODE_VIOLATION)` on any mutating action (click, type, press). Lets agents that only read pages be guaranteed not to accidentally modify state.

**Files:**
- Modify: `grip/errors/types.py` (add `SAFE_MODE_VIOLATION`)
- Modify: `grip/page.py` (accept `_safe` flag, guard mutating methods)
- Modify: `grip/browser.py` (accept `safe` param, pass to Page)
- Modify: `tests/unit/test_error_types.py` (update enum assertion)
- Create: `tests/unit/test_safe_mode.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_safe_mode.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from grip.page import Page
from grip.trace import Trace
from grip.errors.types import GripError, ErrorType


def _make_safe_page():
    engine = MagicMock()
    engine.send = AsyncMock(return_value={})
    return Page(engine=engine, trace=Trace(), safe=True)


@pytest.mark.asyncio
async def test_safe_mode_blocks_click():
    page = _make_safe_page()
    with pytest.raises(GripError) as exc:
        await page.click("Buy Now")
    assert exc.value.error.type == ErrorType.SAFE_MODE_VIOLATION


@pytest.mark.asyncio
async def test_safe_mode_blocks_type():
    page = _make_safe_page()
    with pytest.raises(GripError) as exc:
        await page.type("search", "hello")
    assert exc.value.error.type == ErrorType.SAFE_MODE_VIOLATION


@pytest.mark.asyncio
async def test_safe_mode_blocks_press():
    page = _make_safe_page()
    with pytest.raises(GripError) as exc:
        await page.press("Enter")
    assert exc.value.error.type == ErrorType.SAFE_MODE_VIOLATION


@pytest.mark.asyncio
async def test_safe_mode_allows_snapshot():
    page = _make_safe_page()
    page._engine.send.side_effect = [
        {}, {},
        {"result": {"value": "[]"}},
        {"result": {"value": ""}},
        {"targetInfo": {"title": "Test", "url": "https://example.com"}},
    ]
    snap = await page.snapshot()  # should not raise
    assert snap is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python3 -m pytest tests/unit/test_safe_mode.py -v
```
Expected: FAIL — `TypeError: Page.__init__() got an unexpected keyword argument 'safe'`

- [ ] **Step 3: Add SAFE_MODE_VIOLATION to ErrorType**

In `grip/errors/types.py`:

```python
class ErrorType(Enum):
    ELEMENT_STALE = "element_stale"
    ELEMENT_NOT_FOUND = "element_not_found"
    ANTI_BOT_BLOCK = "anti_bot_block"
    CAPTCHA_REQUIRED = "captcha_required"
    RATE_LIMITED = "rate_limited"
    AUTH_REQUIRED = "auth_required"
    ZERO_RESULTS = "zero_results"
    NETWORK_TIMEOUT = "network_timeout"
    NAVIGATION_FAILED = "navigation_failed"
    CANVAS_ELEMENT = "canvas_element"
    SAFE_MODE_VIOLATION = "safe_mode_violation"
```

- [ ] **Step 4: Update test_error_types.py enum assertion**

In `tests/unit/test_error_types.py`, update `test_all_error_types_exist`:

```python
def test_all_error_types_exist():
    types = {e.value for e in ErrorType}
    expected = {
        "element_stale", "element_not_found",
        "anti_bot_block", "captcha_required", "rate_limited",
        "auth_required", "zero_results",
        "network_timeout", "navigation_failed", "canvas_element",
        "safe_mode_violation",
    }
    assert expected == types
```

- [ ] **Step 5: Add safe mode to Page**

In `grip/page.py`, update `Page.__init__()`:

```python
    def __init__(self, engine: CDPEngine, trace: Trace, target_id: str = "", safe: bool = False) -> None:
        self._engine = engine
        self._trace = trace
        self._target_id = target_id
        self._safe = safe
        self._version = 0
        self._current_snapshot: PageSnapshot | None = None
        self._current_url: str = ""
        self._summarizer = Summarizer()
        self._cache = ElementCache()
        self._diff = SnapshotDiff()
        self._filter = HiddenElementFilter()
        self._injector = InjectionDetector()
        self._classifier = ErrorClassifier()
        self._refs = RefRegistry()
        self._initialized = False
```

Add a private helper to Page:

```python
    def _assert_not_safe(self, action: str) -> None:
        if self._safe:
            raise GripError(BrowserError(
                type=ErrorType.SAFE_MODE_VIOLATION,
                message=f"{action}() is not allowed in safe mode",
                confidence=1.0,
                recovery=[],
            ))
```

Add `from grip.errors.types import ErrorType, BrowserError` to the imports at the top of `grip/page.py` (it already imports `GripError` — add the others).

Call `self._assert_not_safe("click")` as the first line of `click()`, `self._assert_not_safe("type")` in `type()`, `self._assert_not_safe("press")` in `press()`.

- [ ] **Step 6: Add safe param to Browser**

In `grip/browser.py`, update `Browser.__init__()`:

```python
    def __init__(self, llm: "LLMAdapter | None" = None, headless: bool = True, safe: bool = False) -> None:
        self._llm = llm
        self._headless = headless
        self._safe = safe
        self._launcher: ChromeLauncher | None = None
        self._engine: CDPEngine | None = None
        self.trace = Trace()
```

Update both places where `Page(...)` is constructed in `browser.py` (in `open()`):

```python
        return Page(engine=self._engine, trace=self.trace, safe=self._safe)
```

- [ ] **Step 7: Run tests**

```bash
.venv/bin/python3 -m pytest tests/unit/test_safe_mode.py tests/unit/test_error_types.py -v
```
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add grip/errors/types.py grip/page.py grip/browser.py tests/unit/test_safe_mode.py tests/unit/test_error_types.py
git commit -m "feat: safe mode — Browser(safe=True) blocks click/type/press"
```

---

## Task 6: Proxy support

`Browser(proxy="http://host:port")` passes the proxy to Chrome's launch flags.

**Files:**
- Modify: `grip/cdp/launcher.py` (add `proxy` to `launch()`)
- Modify: `grip/browser.py` (add `proxy` param, pass through)
- Create: `tests/unit/test_proxy.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_proxy.py`:

```python
from unittest.mock import patch, MagicMock
from grip.cdp.launcher import ChromeLauncher


def test_proxy_flag_added_to_args():
    launcher = ChromeLauncher.__new__(ChromeLauncher)
    launcher.executable = "/fake/chrome"
    launcher._process = None
    launcher._user_data_dir = None

    with patch("tempfile.mkdtemp", return_value="/tmp/fake"), \
         patch("subprocess.Popen") as mock_popen, \
         patch.object(launcher, "_read_port", return_value=9222):
        mock_popen.return_value = MagicMock()
        launcher.launch(headless=True, proxy="http://proxy.example.com:8080")
        args = mock_popen.call_args[0][0]
        assert any("--proxy-server=http://proxy.example.com:8080" in a for a in args)


def test_no_proxy_flag_when_proxy_is_none():
    launcher = ChromeLauncher.__new__(ChromeLauncher)
    launcher.executable = "/fake/chrome"
    launcher._process = None
    launcher._user_data_dir = None

    with patch("tempfile.mkdtemp", return_value="/tmp/fake"), \
         patch("subprocess.Popen") as mock_popen, \
         patch.object(launcher, "_read_port", return_value=9222):
        mock_popen.return_value = MagicMock()
        launcher.launch(headless=True, proxy=None)
        args = mock_popen.call_args[0][0]
        assert not any("--proxy-server" in a for a in args)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python3 -m pytest tests/unit/test_proxy.py -v
```
Expected: FAIL — `TypeError: ChromeLauncher.launch() got an unexpected keyword argument 'proxy'`

- [ ] **Step 3: Add proxy to ChromeLauncher.launch()**

In `grip/cdp/launcher.py`, update `launch()`:

```python
    def launch(self, headless: bool = True, proxy: str | None = None) -> int:
        self._user_data_dir = tempfile.mkdtemp(prefix="grip_chrome_")
        args = [
            self.executable,
            "--remote-debugging-port=0",
            f"--user-data-dir={self._user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
        ]
        if headless:
            args.append("--headless=new")
        if proxy:
            args.append(f"--proxy-server={proxy}")
        self._process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        port = self._read_port()
        return port
```

- [ ] **Step 4: Add proxy to Browser**

In `grip/browser.py`, update `Browser.__init__()`:

```python
    def __init__(
        self,
        llm: "LLMAdapter | None" = None,
        headless: bool = True,
        safe: bool = False,
        proxy: str | None = None,
    ) -> None:
        self._llm = llm
        self._headless = headless
        self._safe = safe
        self._proxy = proxy
        self._launcher: ChromeLauncher | None = None
        self._engine: CDPEngine | None = None
        self.trace = Trace()
```

Update both launcher calls in `Browser` to pass proxy:

```python
        port = self._launcher.launch(headless=self._headless, proxy=self._proxy)
```

(This appears in `__aenter__` and in the lazy-init block inside `open()`.)

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python3 -m pytest tests/unit/test_proxy.py tests/unit/test_launcher.py -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add grip/cdp/launcher.py grip/browser.py tests/unit/test_proxy.py
git commit -m "feat: proxy support — Browser(proxy='http://host:port')"
```

---

## Task 7: Session persistence

`browser.save_session(path)` saves cookies to JSON. `browser.load_session(path)` restores them. Lets agents stay logged in across runs.

**Files:**
- Modify: `grip/browser.py` (add `save_session`, `load_session`)
- Create: `tests/unit/test_session.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_session.py`:

```python
import json
import pytest
import tempfile
import os
from unittest.mock import AsyncMock, MagicMock, patch
from grip.browser import Browser


def _make_browser_with_engine(send_side_effect):
    browser = Browser.__new__(Browser)
    browser._llm = None
    browser._headless = True
    browser._safe = False
    browser._proxy = None
    browser._launcher = None
    from grip.trace import Trace
    browser.trace = Trace()
    engine = MagicMock()
    engine.send = AsyncMock(side_effect=send_side_effect)
    browser._engine = engine
    return browser


@pytest.mark.asyncio
async def test_save_session_writes_cookies():
    cookies = [
        {"name": "session", "value": "abc123", "domain": "example.com",
         "path": "/", "expires": -1, "size": 14, "httpOnly": True,
         "secure": True, "session": True, "sameSite": "None"}
    ]
    browser = _make_browser_with_engine([{"cookies": cookies}])
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        await browser.save_session(path)
        with open(path) as f:
            saved = json.load(f)
        assert saved == cookies
    finally:
        os.unlink(path)


@pytest.mark.asyncio
async def test_load_session_sends_set_cookies():
    cookies = [
        {"name": "session", "value": "abc123", "domain": "example.com",
         "path": "/", "expires": -1, "size": 14, "httpOnly": True,
         "secure": True, "session": True, "sameSite": "None"}
    ]
    browser = _make_browser_with_engine([{}, {}])  # Network.enable, Network.setCookies
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(cookies, f)
        path = f.name
    try:
        await browser.load_session(path)
        calls = browser._engine.send.call_args_list
        methods = [c[0][0] for c in calls]
        assert "Network.enable" in methods
        assert "Network.setCookies" in methods
        set_cookies_call = next(c for c in calls if c[0][0] == "Network.setCookies")
        assert set_cookies_call[0][1]["cookies"] == cookies
    finally:
        os.unlink(path)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python3 -m pytest tests/unit/test_session.py -v
```
Expected: FAIL — `AttributeError: 'Browser' object has no attribute 'save_session'`

- [ ] **Step 3: Add save_session and load_session to Browser**

In `grip/browser.py`, add after `close()`:

```python
    async def save_session(self, path: str) -> None:
        result = await self._engine.send("Network.getCookies", {})
        cookies = result.get("cookies", [])
        with open(path, "w") as f:
            json.dump(cookies, f, indent=2)

    async def load_session(self, path: str) -> None:
        with open(path) as f:
            cookies = json.load(f)
        await self._engine.send("Network.enable", {})
        await self._engine.send("Network.setCookies", {"cookies": cookies})
```

Add `import json` to the top of `grip/browser.py` (it's already there from `fetch_tab_ws_url` — confirm and keep).

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python3 -m pytest tests/unit/test_session.py -v
```
Expected: all PASS

- [ ] **Step 5: Run full unit suite to check for regressions**

```bash
.venv/bin/python3 -m pytest tests/unit/ -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add grip/browser.py tests/unit/test_session.py
git commit -m "feat: session persistence — save_session/load_session for cookie auth"
```

---

## Final step: Bump version and push

- [ ] **Update version in pyproject.toml**

```toml
[project]
version = "0.2.0"
```

- [ ] **Update __init__.py to export new symbols**

In `grip/__init__.py`:

```python
from grip.browser import Browser
from grip.compression.summarizer import Element, PageSnapshot
from grip.compression.refs import RefRegistry
from grip.errors.types import BrowserError, ErrorType, GripError, RecoveryAction
from grip.page import Screenshot
from grip.trace import Trace, TraceEntry

__all__ = [
    "Browser",
    "PageSnapshot",
    "Element",
    "RefRegistry",
    "BrowserError",
    "ErrorType",
    "GripError",
    "RecoveryAction",
    "Screenshot",
    "Trace",
    "TraceEntry",
]

__version__ = "0.2.0"
```

- [ ] **Run full test suite**

```bash
.venv/bin/python3 -m pytest tests/ -v
```
Expected: all pass (95 existing + new tests)

- [ ] **Build and publish**

```bash
.venv/bin/python3 -m build
TWINE_USERNAME=__token__ TWINE_PASSWORD=<token> .venv/bin/python3 -m twine upload dist/grip_browser-0.2.0*
```

- [ ] **Tag and push**

```bash
git add pyproject.toml grip/__init__.py
git commit -m "chore: bump to v0.2.0"
git tag v0.2.0
git push && git push --tags
```
