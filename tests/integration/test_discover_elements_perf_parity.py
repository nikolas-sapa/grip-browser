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
element lists are identical (same elements, same order, same fields).

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
    await page._engine.send(
        "Runtime.evaluate",
        {
            "expression": f"document.open('text/html','replace');document.write({json.dumps(html)});document.close();",
            "returnByValue": True,
        },
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


async def _assert_identical(page) -> None:
    old = await _eval_elements(page, OLD_DISCOVER_ELEMENTS_JS)
    new = await _eval_elements(page, DISCOVER_ELEMENTS_JS)
    assert new == old, (
        f"DISCOVER_ELEMENTS_JS output diverged from pre-optimization baseline.\n"
        f"old ({len(old)}): {old}\nnew ({len(new)}): {new}"
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
    new = await _eval_elements(page, DISCOVER_ELEMENTS_JS)
    old2 = await _eval_elements(page, OLD_DISCOVER_ELEMENTS_JS)
    if old1 != old2:
        return False  # page moved between evals — inconclusive, not a failure
    assert new == old1, (
        f"DISCOVER_ELEMENTS_JS output diverged from pre-optimization baseline "
        f"(page was stable across both OLD evals, so this is real).\n"
        f"old ({len(old1)}): {old1}\nnew ({len(new)}): {new}"
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
    nested.innerHTML = '<input placeholder="nested shadow input" style="display:block;width:100px;height:20px" />';
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
