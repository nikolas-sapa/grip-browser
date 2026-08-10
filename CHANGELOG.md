# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Removed

- **`Page.extract()` and `Page.observe()`.** Breaking. `extract()` returned the
  identical `text_content` for every key in the schema it was given, and
  `observe()` discarded its `question` argument and returned `format(snapshot)`
  — the snapshot tool under a second name. Both were advertised to the model in
  the agent tool list, so a run could spend a turn and its tokens on either and
  learn nothing new. Use `read()` for prose and `snapshot()` for what is
  actionable; `Browser.run(goal, llm=...)` remains the structured-extraction
  path.
- `RefRegistry` from the public exports. It has one internal caller and was
  never usable on its own.

### Added

- **Snapshot deltas.** From the second observation of a page onward, an agent
  can be handed only what changed: elements added, removed and retitled keyed by
  ref, plus word-run diffs of the body text. `Page.delta` exposes it and the
  agent loop uses it automatically. Measured on a five-turn click loop over a
  28-element page: 628 tokens per turn becomes 42, a 75% cut in per-turn
  payload. The loop also stops re-sending superseded page states, which moves
  prompt cost from quadratic in turn count to linear.
- **`NavigationPolicy`.** `Browser` now refuses non-http(s) schemes, private and
  loopback addresses, and cloud metadata endpoints by default. `allow_private`
  and `allow_file` opt back in per browser. Callers that pass user-supplied URLs
  to `open()` were previously exposed to SSRF and local file disclosure.
- **Persistent profiles and remote attach.** `Browser(user_data_dir=...)` reuses
  a profile directory across runs, carrying localStorage, IndexedDB and service
  workers that cookie JSON never could. `Browser(cdp_url=...)` attaches to a
  browser grip did not launch, local or remote.
- **Challenge handling.** `page.detect_challenge()` classifies the stage;
  `page.solve_challenge()` attempts checkbox, Turnstile and slider in-process
  with human-shaped pointer motion, and reports success only where it can verify
  it. Image-grid and text challenges return to the caller's model with a
  screenshot. No third-party solving service is involved. Solve rates are
  unmeasured.
- **`grip.input`** — Bézier pointer paths with eased velocity, for interactions
  where constant-velocity straight-line motion is itself a tell.
- **Optional MCP server.** `pip install "grip-browser[mcp]"` then `grip-mcp`.
  Serves the delta payload the same way the agent loop does.
- `PageSnapshot.prompt_injection` so a caller can tell a page whose text was
  stripped from one that was clean.

### Fixed

- **`click()` and `type()` could still act on the wrong element.** 0.4.2 made
  the three JS collectors agree on which elements are addressable, but the index
  itself remained positional: it was resolved against a cached snapshot and then
  re-derived against the live DOM at action time. Anything inserted or removed
  above the target in between shifted it onto a different element, silently, and
  the action reported success. Elements now carry a `data-grip-h` handle stamped
  at discovery, actions resolve that handle and verify the element's tag and
  text before acting, and a mismatch raises `ELEMENT_STALE` instead of clicking
  something else.
- **The cached snapshot outlived its document.** It was written once and never
  invalidated, so an action after `goto()` resolved against the previous page.
- **`type()` reported success unconditionally.** The CDP result was discarded and
  `success: True` written into the trace regardless of what happened.
- **Duplicate labels collapsed onto one ref.** Refs were `md5(tag:text)`, so two
  "Delete" buttons shared one and the second was unreachable. A hidden element
  sharing a visible control's label could absorb clicks meant for it. Refs are
  now keyed on the element handle.
- **Hidden text reached the model.** Visibility was tested with
  `getComputedStyle().opacity`, which does not inherit, so a child of an
  `opacity:0` parent passed as visible. Uses `checkVisibility()` now.

  Two consequences worth knowing, both deliberate. Elements positioned fully
  off-canvas to the left or top are now treated as hidden — that is the fix for
  the off-screen decoy, where an invisible control sharing a visible one's label
  absorbed clicks meant for it. Only *fully* off-canvas counts; below-the-fold
  elements are still collected, since treating them as hidden would gut
  snapshots of long pages. The visible cost is that 1×1 accessibility skip links
  (`Jump to content` and friends) no longer appear in snapshots. Separately,
  `color: transparent` reads as hidden **except** when paired with
  `background-clip: text`, which is how gradient-text CTAs are built — without
  that exception the primary button on many sites would vanish from snapshots.
- **Chrome and its profile directory leaked** when a connect failed, when
  `close()` hit a raising `disconnect()`, and once per extra caller when several
  coroutines opened the first tab concurrently — the pattern the README itself
  documents.
- **A dead CDP transport left every in-flight call to time out.** Pending futures
  now fail immediately with the connection error rather than each waiting out the
  full 30 seconds and reporting a misleading timeout.
- **`goto(timeout=...)` bounded only the load wait,** not the CDP calls in front
  of it, so a one-second timeout could block for ninety.
- **`launch()` and `terminate()` blocked the event loop,** stalling every other
  tab in a concurrent run.
- **One tool error ended the whole agent run.** Errors now return to the model as
  tool results carrying their suggested recovery, and the loop continues. The
  LLM call is bounded; it previously had no timeout inside a twenty-step loop.
- **Prompt injection.** The guard normalises confusable characters, zero-width
  joiners and whitespace before matching, closing nine measured bypasses, and
  scans the page title, element text and placeholders — channels that reached the
  model entirely unscanned. Page content is now delimited and framed as untrusted
  data in the system prompt, which is the defense that does not depend on
  enumerating attacks; the pattern list remains a filter, not a control.
- **Typed text was persisted to traces** at 0644, passwords included. It is
  redacted at entry. Session cookie files are created 0600.
- **`find_chrome()` trusted `CHROME_EXECUTABLE` without checking it existed,** so
  a stale value produced an opaque failure deep in `launch()` instead of the
  clear "Chrome/Chromium not found" error.

### Changed

- Browser-dependent tests skip when no Chrome is present instead of failing. 98
  of them used to produce a wall of errors that read as a broken library.
- `ruff` and `mypy` are now configured. Both previously passed by running with
  default rule sets over a codebase with 68 and 25 real findings respectively; a
  gate that reports safety nobody checked is worse than no gate. Both are clean.
- CI tests Python 3.14.
- Removed dead code: the fingerprint-only `diff.py` (superseded by deltas, and it
  truncated at 500 characters while snapshots carry 8000), `ElementCache` (never
  read), `HiddenElementFilter` (never called, and the fields it read were never
  populated), `Element.snapshot_version` (never compared), and a duplicate
  tokenization pass per snapshot.

### Known limitations

- TLS/JA3 fingerprints and full headless fingerprint parity are below the
  DevTools Protocol and out of reach from Python driving stock Chromium. A site
  blocking on IP reputation needs a residential or mobile proxy, which `proxy=`
  supports.
- Whether `stealth=True` helps is unmeasured. `evaluation/stealth_measurement.py`
  answers it where a browser has network access.
- A `SIGKILL`ed process still strands its temp profile directory; `terminate()`
  cannot run if the interpreter never regains control.

## [0.4.2] - 2026-08-06

### Fixed

- **`click()` and `type()` could act on the wrong element.** Both are handed an index
  produced by `snapshot()`, but each built its own candidate list by different rules.
  `DISCOVER_ELEMENTS_JS` treated an element as hidden on six conditions (display,
  visibility, opacity, aria-hidden, zero width, zero height); `CLICK_ELEMENT_JS`
  checked two; `TYPE_ELEMENT_JS` collected an entirely different, input-only set and
  ignored the snapshot's ordering altogether.

  On any page containing an `aria-hidden` or `opacity:0` control, click landed on a
  different element than the one matched. Typing was worse: an input preceded by
  buttons or links sat at a different index in `TYPE`'s list than the snapshot
  reported, so text went to the wrong field. Existing tests passed only because every
  fixture happened to put the input first.

  All three now index into one shared collector, so the lists cannot drift apart
  again. `type()` additionally returns false rather than silently doing nothing if
  the addressed element is not typable. Verified by regression tests that fail
  against the previous implementation (4 of 5) and pass against this one.

### Changed

- The tracking-iframe unit test asserted internal JavaScript variable names and broke
  on a pure refactor while the behaviour was intact. It now asserts the host list,
  with the behaviour itself covered by an integration test.

### Note on 0.4.1's performance claim

0.4.1 reported element discovery 1.14x-2.27x faster on real pages, which holds. It is
worth recording what it does *not* claim: on a deliberately dense benchmark fixture
(3000 interactive elements, ~60% of all nodes), the change is inside measurement
noise. Roughly 95% of that fixture's cost is `getComputedStyle`,
`getBoundingClientRect` and `innerText` on elements that genuinely are candidates —
load-bearing for the output and not removable without changing what is returned. The
speedup comes from skipping that work on non-candidates, so it scales with how
sparse the page is, and real pages are sparse.

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
