"""
Differential test for the DISCOVER_ELEMENTS_JS perf optimization
(grip/cdp/shadow.py). The optimization reorders per-node work so that
getComputedStyle/getBoundingClientRect/offsetWidth/offsetHeight — the
expensive, layout-forcing calls — only run for elements that already match
INTERACTIVE_TAGS/INTERACTIVE_ROLES, instead of running unconditionally for
every element the TreeWalker visits.

This test proves that reorder is a pure cost change, not a behaviour change:
it runs both the pre-optimization JS (frozen below, verbatim) and the current
DISCOVER_ELEMENTS_JS against the same live DOM and asserts the returned
element lists are identical (same elements, same order, same fields) apart from
the two changes that have landed deliberately since the baseline was frozen —
see the KNOWN_NEW_FIELDS comment below.

Injects HTML into about:blank so most cases need no network; a handful of
real pages (reused from evaluation/corpus.py) are included for messier,
real-world DOM shapes. Network fetches are best-effort: a page that fails to
load is skipped rather than failing the whole suite on a flaky connection.
"""
import asyncio
import json

import pytest

from grip.browser import Browser
from grip.cdp.shadow import DISCOVER_ELEMENTS_JS

# Frozen copy of DISCOVER_ELEMENTS_JS as it stood before the perf reorder.
# getComputedStyle/getBoundingClientRect/offsetWidth/offsetHeight ran for
# every node visited, not just tag/role candidates. Do not "fix" this to
# match the new version — it exists to be different.
OLD_DISCOVER_ELEMENTS_JS = """
(function() {
  const results = [];
  let idx = 0;

  const INTERACTIVE_TAGS = new Set([
    'a','button','input','select','textarea','details','summary'
  ]);
  const INTERACTIVE_ROLES = new Set([
    'button','link','checkbox','radio','menuitem','tab','textbox',
    'combobox','listbox','option','switch','treeitem','slider'
  ]);

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
        let _iframeHost = '';
        try { _iframeHost = new URL(src, location.href).hostname; } catch(e) {}
        const isTracking = [
          'googletagmanager.com', 'google-analytics.com', 'facebook.net',
          'hotjar.com', 'sentry.io', 'recaptcha.net', 'doubleclick.net',
          'analytics.google.com', 'pixel.facebook.com', 'tr.snapchat.com'
        ].some(p => _iframeHost.includes(p));
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
          href: (function () {
            if (tag !== 'a') return null;
            const raw = el.getAttribute('href');
            if (!raw || raw.startsWith('#')) return null;
            const abs = el.href;
            return /^https?:/i.test(abs) ? abs : null;
          })(),
          inShadowDom: inShadow,
          cx: Math.round(rect.left + rect.width / 2),
          cy: Math.round(rect.top + rect.height / 2),
          // Diagnostic only, stripped before comparison and not part of the
          // frozen selection logic: reports whether the current collector's
          // off-canvas rule would suppress this element. See
          // _diff_against_baseline for why that has to be checked per element
          // rather than allowed categorically.
          offCanvas: (
            rect.right + window.scrollX <= 0 || rect.bottom + window.scrollY <= 0
          ),
        });
      }

      if (el.shadowRoot) {
        collectElements(el.shadowRoot, true);
      }
      node = walker.nextNode();
    }
  }

  collectElements(document.body, false);
  return results;
})();
"""


async def open_with_html(browser: Browser, html: str):
    page = await browser.open("about:blank")
    expr = (
        f"document.open('text/html','replace');"
        f"document.write({json.dumps(html)});document.close();"
    )
    await page._engine.send(
        "Runtime.evaluate",
        {"expression": expr, "returnByValue": True},
    )
    await asyncio.sleep(0.15)
    return page


async def _eval_elements(page, js: str) -> list[dict]:
    result = await page._engine.send(
        "Runtime.evaluate", {"expression": js, "returnByValue": True}
    )
    value = result.get("result", {}).get("value")
    if isinstance(value, str):
        value = json.loads(value)
    return value or []


# Four things have deliberately changed since the baseline was frozen, and
# exactly four. All are subtracted/filtered here so the test keeps failing on
# anything else.
#
# 1. `handle` — the data-grip-h stamp added so click/type act on the element the
#    caller was actually shown rather than on whatever now occupies that index.
#    A pure field addition, so it is dropped before comparing.
# 2. Off-canvas suppression — the current gripIsHidden also rejects elements
#    lying entirely at negative document coordinates (Wikipedia's and MDN's 1x1
#    "Skip to content" links, e.g.). That drops *elements*, not fields, and
#    element loss is the exact drift this test exists to catch, so it is not
#    allowed categorically: each missing element must individually satisfy the
#    off-canvas predicate, re-evaluated in the page by the baseline JS itself.
# 3. Per-element interaction state (`disabled`/`required`/`checked`/`selected`/
#    `value`) — pure field additions, dropped before comparing, same as `handle`.
#    Plus iframe stub rows (`tag === 'iframe'`): the baseline never emits these
#    (iframe is not in INTERACTIVE_TAGS/ROLES), so they are filtered out of the
#    current collector's output before the two are diffed, rather than expected
#    to line up against a baseline row that was never going to exist.
# 4. Label inference (grip/cdp/shadow.py's gripInferredLabel) — a form control
#    with no aria-labelledby/aria-label/native <label> used to get `text: ''`;
#    the current collector now falls back through placeholder/title/sibling
#    text/humanized name-id, so `text` goes from empty to non-empty for those
#    rows specifically. Handled narrowly in _rows_match_allowing_inferred_label
#    below (baseline text must have been '' and every other field must still
#    match) rather than by dropping `text` from the comparison generally, so a
#    real drift in an already-labelled element's text still fails the test.
#
# The current collector may never contain a non-iframe element the baseline
# lacks, and every surviving element must match field-for-field, in order.
KNOWN_NEW_FIELDS = frozenset({"handle", "disabled", "required", "checked", "selected", "value"})
DIAGNOSTIC_OLD_FIELDS = frozenset({"offCanvas"})


def _comparable(row: dict, drop: frozenset[str]) -> dict:
    # `index` is positional, so a justified drop renumbers everything after it.
    # It is re-derived from the aligned sequences instead of compared directly.
    return {k: v for k, v in row.items() if k not in drop and k != "index"}


def _rows_match_allowing_inferred_label(o: dict, n: dict) -> bool:
    """True if `o` (baseline) and `n` (current) agree outright, or agree on
    every field except `text` where the divergence is exactly the deliberate
    label-inference change: baseline had no text at all, current has some.
    Anything else — baseline already had text and it changed, or some other
    field also diverged — is a real mismatch, not this allowance."""
    if o == n:
        return True
    if o.get("text") == "" and n.get("text"):
        return {**o, "text": n["text"]} == n
    return False


def _diff_against_baseline(old: list[dict], new: list[dict]) -> str | None:
    """Returns a failure description, or None if the two agree modulo the
    deliberate changes above. Walks both in order: the current collector's rows
    must appear in the baseline's order, and any baseline row skipped over has
    to be one the off-canvas rule legitimately suppresses."""
    for row in new:
        if not row.get("handle"):
            return f"expected a non-empty element handle, got {row!r}"

    i = j = 0
    while i < len(old) and j < len(new):
        o = _comparable(old[i], DIAGNOSTIC_OLD_FIELDS)
        n = _comparable(new[j], KNOWN_NEW_FIELDS)
        if _rows_match_allowing_inferred_label(o, n):
            i += 1
            j += 1
        elif old[i]["offCanvas"]:
            i += 1  # legitimately suppressed by the off-canvas rule
        else:
            return (
                f"element {j} differs and the baseline element {i} it should have "
                f"matched is on-canvas, so this is a real divergence.\n"
                f"baseline: {o}\ncurrent:  {n}"
            )
    if j < len(new):
        return f"current collector has {len(new) - j} element(s) the baseline lacks: {new[j:]}"
    unjustified = [r for r in old[i:] if not r["offCanvas"]]
    if unjustified:
        return f"current collector dropped on-canvas element(s): {unjustified}"
    return None


def _drop_iframe_rows(rows: list[dict]) -> list[dict]:
    """Iframe stub rows are new-only (see KNOWN_NEW_FIELDS note 3): the baseline
    JS never produces them, so they are excluded before diffing rather than
    expected to match a baseline row that cannot exist."""
    return [r for r in rows if r.get("tag") != "iframe"]


async def _assert_identical(page) -> None:
    old = await _eval_elements(page, OLD_DISCOVER_ELEMENTS_JS)
    new = _drop_iframe_rows(await _eval_elements(page, DISCOVER_ELEMENTS_JS))
    problem = _diff_against_baseline(old, new)
    assert problem is None, (
        f"DISCOVER_ELEMENTS_JS output diverged from pre-optimization baseline.\n"
        f"{problem}\nold ({len(old)}) / new ({len(new)})"
    )


async def _assert_identical_or_page_moved(page) -> bool:
    """Same check as _assert_identical, but self-consistent against a live
    page: eval OLD, then NEW, then OLD again. A real page can legitimately
    mutate itself between evals (hydration, A/B-experiment href rewrites,
    mid-transition opacity) for reasons that have nothing to do with this
    JS change. If OLD disagrees with itself (old1 != old2) the page moved
    under us — that run is inconclusive, not a failure. Only old1==old2!=new
    is a real divergence. Returns True if the comparison was conclusive.
    """
    old1 = await _eval_elements(page, OLD_DISCOVER_ELEMENTS_JS)
    new = _drop_iframe_rows(await _eval_elements(page, DISCOVER_ELEMENTS_JS))
    old2 = await _eval_elements(page, OLD_DISCOVER_ELEMENTS_JS)
    if old1 != old2:
        return False  # page moved between evals — inconclusive, not a failure
    problem = _diff_against_baseline(old1, new)
    assert problem is None, (
        f"DISCOVER_ELEMENTS_JS output diverged from pre-optimization baseline "
        f"(page was stable across both OLD evals, so this is real).\n"
        f"{problem}\nold ({len(old1)}) / new ({len(new)})"
    )
    return True


SHADOW_HTML = """
<html><body style="margin:0;padding:20px">
  <div id="host" style="display:block"></div>
  <script>
    const host = document.getElementById('host');
    const shadow = host.attachShadow({mode: 'open'});
    shadow.innerHTML = `
      <button style="display:block;width:120px;height:36px">Shadow Button</button>
      <a href="/shadow-link" style="display:block">Shadow Link</a>
      <button style="opacity:0">Hidden Shadow Button</button>
      <button aria-hidden="true">Aria-Hidden Shadow Button</button>
      <div id="nested-host"></div>
    `;
    const nested = shadow.getElementById('nested-host').attachShadow({mode: 'open'});
    nested.innerHTML =
      '<input placeholder="nested shadow input" style="display:block;width:100px;height:20px" />';
  </script>
</body></html>
"""

HIDDEN_HTML = """
<html><body>
  <button style="display:none">display none</button>
  <button style="visibility:hidden">visibility hidden</button>
  <button style="opacity:0">opacity zero</button>
  <button aria-hidden="true">aria hidden</button>
  <button style="width:0;height:0">zero size</button>
  <button>Visible Button</button>
  <a href="/ok">Visible Link</a>
  <div role="button" aria-hidden="true">hidden role button</div>
  <div role="button">Visible Role Button</div>
  <input placeholder="visible input" />
  <textarea style="display:none"></textarea>
  <details><summary>Visible Summary</summary>content</details>
</body></html>
"""


def _build_dense_html(n_interactive: int, n_paragraphs: int) -> str:
    """Mirrors benchmarks/bench_grip.py's synthetic fixtures: lots of
    interactive elements interleaved with prose."""
    parts = ["<html><body><main>", "<h1>Fixture</h1>"]
    for i in range(n_paragraphs):
        parts.append(f"<p>Paragraph {i} with representative prose text {i}.</p>")
    for i in range(n_interactive):
        kind = i % 4
        if kind == 0:
            parts.append(f'<button id="b{i}">Button {i}</button>')
        elif kind == 1:
            parts.append(f'<a href="/page/{i}">Link {i}</a>')
        elif kind == 2:
            parts.append(f'<input placeholder="field {i}" />')
        else:
            parts.append(f'<select><option>opt{i}</option></select>')
    parts.append("</main></body></html>")
    return "".join(parts)


def _build_sparse_html(n_wrappers: int, n_interactive: int) -> str:
    """Realistic DOM shape: many non-interactive wrapper divs/spans around a
    small number of interactive elements — the shape this optimization
    targets, since dense synthetic fixtures under-represent it."""
    parts = ["<html><body><main>"]
    for i in range(n_wrappers):
        parts.append(f'<div class="wrap{i}"><span>text {i}</span></div>')
    for i in range(n_interactive):
        parts.append(f'<button id="b{i}">Button {i}</button>')
    parts.append("</main></body></html>")
    return "".join(parts)


LOCAL_FIXTURES = {
    "shadow_dom": SHADOW_HTML,
    "hidden_elements": HIDDEN_HTML,
    "dense_small": _build_dense_html(n_interactive=20, n_paragraphs=10),
    "dense_medium": _build_dense_html(n_interactive=300, n_paragraphs=100),
    "sparse_large": _build_sparse_html(n_wrappers=2000, n_interactive=150),
}


@pytest.mark.asyncio
async def test_discover_elements_matches_baseline_on_local_fixtures():
    async with Browser(headless=True) as browser:
        for name, html in LOCAL_FIXTURES.items():
            page = await open_with_html(browser, html)
            try:
                await _assert_identical(page)
            except AssertionError as e:
                raise AssertionError(f"fixture={name}: {e}") from e
            finally:
                await page.close()


# A handful of real, messy pages (reused from evaluation/corpus.py) to catch
# anything the synthetic fixtures don't: deeply nested wrapper markup, custom
# elements, aria-heavy widgets, iframes. Best-effort — a page that fails to
# load (network flake) is skipped, not failed, so this stays CI-safe.
REAL_URLS = [
    "https://en.wikipedia.org/wiki/Headless_browser",
    "https://news.ycombinator.com",
    "https://react.dev/learn",
    "https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API",
    "https://github.com/python/cpython",
]


@pytest.mark.network
@pytest.mark.asyncio
async def test_discover_elements_matches_baseline_on_real_pages():
    checked = 0
    async with Browser(headless=True) as browser:
        for url in REAL_URLS:
            try:
                page = await asyncio.wait_for(browser.open(url), timeout=20.0)
            except Exception:
                continue  # network flake — not what this test is proving
            try:
                # Some real pages (Wikipedia's footnote backlinks, e.g.) mutate
                # aria-label/href/opacity asynchronously after load via their
                # own JS (hydration, A/B-experiment rewrites, CSS transitions)
                # — independent of anything under test here. A fixed sleep
                # narrows that window but can't close it on a slower box, so
                # the comparison itself is made self-consistent instead: OLD
                # is evaluated before and after NEW, and only a real
                # old==old!=new divergence fails the test. If the page moved
                # between the two OLD evals, that run is inconclusive and is
                # retried once rather than counted as a failure.
                await asyncio.sleep(1.0)
                conclusive = await _assert_identical_or_page_moved(page)
                if not conclusive:
                    await asyncio.sleep(0.5)
                    conclusive = await _assert_identical_or_page_moved(page)
                if conclusive:
                    checked += 1
            except AssertionError as e:
                raise AssertionError(f"url={url}: {e}") from e
            finally:
                await page.close()
    assert checked >= 1, "no real page loaded/settled — cannot confirm parity on live DOM"
