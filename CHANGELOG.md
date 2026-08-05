# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
