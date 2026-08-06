# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.4.1] - 2026-08-06

### Changed

- `DISCOVER_ELEMENTS_JS` now resolves computed style and layout only for elements
  that are interactive candidates, instead of for every node it walks.
  `getComputedStyle`, `offsetWidth`/`offsetHeight` and `getBoundingClientRect` force
  style resolution and layout, and were previously paid on every element in the DOM
  even though the result was only ever consulted inside the tag/role check. Measured
  1.14x-2.27x faster on real pages (Python docs 25.8ms -> 11.6ms, react.dev
  17.3ms -> 7.6ms), with element output verified byte-identical across five sites.

### Fixed

- Cleared the entire lint and type backlog in `grip/`: 39 ruff findings and 10 mypy
  errors down to zero, with no test modified. Notably a real forward-reference bug
  (`RunResult` undefined in `browser.py`) and a stale websockets type annotation
  (`WebSocketClientProtocol`, which the installed version no longer exports).
  `CDPEngine.send()` now raises a clear error when called before `connect()` rather
  than failing on a `None` attribute.
- CI's lint job is now a real gate at zero rather than a ratchet against a backlog.

## [0.4.0] - 2026-08-06

### Added

- `Browser(block_resources=True)` — opt-in blocking of images, fonts and media via
  `Network.setBlockedURLs`. CSS and XHR are deliberately not blocked: layout decides
  which elements count as visible, and content routinely arrives over XHR. Measured
  across 50 real pages, blocking is what makes browser-driven retrieval cheaper than
  a static-fetch vendor for text-oriented content (see `evaluation/PAGE_WEIGHT.md`).
- `ErrorType.NO_CONTENT` — a third fetch outcome distinct from success and from a
  block: the page loaded, was not blocked, and has no usable content. Detected from
  soft-404 titles and from a content-shape signal comparing raw page text against
  what survives chrome stripping. Validated against 33 real pages with zero false
  positives.

### Changed

- `snapshot()` now issues its three independent CDP calls concurrently rather than
  sequentially — measured 15-30% faster on local fixtures, no behaviour change.
- The content-shape probe runs once per URL rather than once per snapshot. It costs
  a second JS evaluation, and its verdict describes the fetch, so re-deriving it
  after an agent has been interacting with the page cannot change the answer
  (16.1ms -> 10.2ms median).

### Fixed

- `Browser.open()` no longer leaks a tab and its websocket when navigation fails or
  the caller cancels mid-navigate. Previously the `Page` was registered before
  `goto()` ran, so a cancelled `open()` left a tab open with no handle for the caller
  to close it — at ~219 MB per tab, this accumulated for the lifetime of the browser.
- `read(interact=True)` now respects safe mode. Revealing content means clicking, and
  the interaction path bypassed the guard that `click()`/`type()`/`press()` enforce.
- Removed `"please wait"` and `"forbidden"` from anti-bot title detection. Both match
  ordinary titles ("Forbidden fruit"), and a false positive causes a legitimate page
  to be dropped unread. Real 403s are caught by status code.
- The source distribution no longer bundles the separate `grip-search` package. The
  wheel's package filter does not apply to sdists.

## [0.3.0] - 2026-08-05

### Added

- Concurrent pages: every `browser.open()` gets its own tab and its own CDP
  connection, so pages can be driven in parallel. Added `page.goto()` to
  navigate an existing tab in place, and `page.close()` to close a tab.
  `Browser.close()` now closes any tabs left open.
- `Element.href` and `PageSnapshot.links` — links now report their destination
  (absolute, http(s) only).
- `page.read()` read mode: main-content isolation, chrome stripping, and
  citable blocks carrying a heading breadcrumb, so a claim can be cited back
  to a location. Removed the old 8000-char truncation.
- `Browser(stealth=True)`: opt-in removal of `navigator.webdriver` and the
  `HeadlessChrome` UA string. Off by default.
- Chrome discovery now falls back to Playwright's or Puppeteer's cached
  Chrome for Testing build if no system Chrome is found.
- Added `"just a moment"` and other interstitial page titles to block
  detection.

### Changed

- **Breaking:** a second `open()` now returns an independent tab instead of
  clobbering the first.
- **Breaking:** `save_session`/`load_session` moved from the `Network` to the
  `Storage` CDP domain. The browser-level endpoint has no `Network` domain,
  and `Storage` also returns every cookie rather than only the ones scoped to
  one tab.

### Fixed

- Load-event race: `open()` subscribed to `Page.loadEventFired` after calling
  `Page.navigate`, losing the race on every fast page and waiting out the
  full 30s timeout. A real-page test went from 59s to 2.2s.
- Blocked fetches no longer report success: the real HTTP status is now
  captured from `Network.responseReceived`. Previously status was hardcoded
  to 0, making the 429 and 403 branches unreachable dead code.
- Launcher robustness: `terminate()` now escalates to `kill()`, and
  `_read_port()` no longer parses a partially-written `DevToolsActivePort`
  file.
