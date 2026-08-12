# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.8.1] - 2026-08-12

Measurement release. Two things the site called "unmeasured" got measured,
and the measuring found real bugs.

### Fixed

- **The slider solver never worked.** `SLIDER_PROBE_JS` resolved the track
  with `handle.closest('[class*="slider"]')`, which matched the handle
  itself (its own class contains "slider"), so the drag distance collapsed
  to roughly zero and every attempt timed out — including on markup
  matching grip's own documented geetest example. The track is now resolved
  from a genuine ancestor wider than the handle, and bails with a stated
  reason instead of silently dragging nothing. Benchmarked 0/5 → 5/5.
- **Two challenge classifier false positives**, both deterministic: ordinary
  prose containing "solve a captcha puzzle" classified as a challenge, and a
  documentation page merely quoting the `cf-turnstile` embed snippet as text
  classified as Turnstile. False-positive rate on the negative fixtures went
  10/40 → 0/40.
- **The stealth user agent was pinned to a Chrome version that was not
  running.** `_STEALTH_UA` hardcoded `Chrome/149` while the launched binary
  was 151 — self-inconsistent, and worse with every Chrome release. It is
  now derived from `Browser.getVersion()` at runtime, applied via
  `Network.setUserAgentOverride` so it fixes the outgoing request header and
  not only `navigator.userAgent`, and re-applied to popup targets.

### Added

- **`benchmarks/bench_challenges.py`** with 26 local fixtures: measures
  classification accuracy (including negatives, so false positives count),
  solve rate, and whether a "solved" claim is ever false. Across 30 solve
  runs, zero false-solved — the "reports solved only when verified" claim
  holds up.
- **`benchmarks/bench_stealth_signals.py`**, which reads bot.sannysoft's own
  57-row result table rather than regexing page text.

### Measured

On real Chrome for Testing 151, macOS arm64, `--headless=new`: 5 of 57
sannysoft signals failed with stealth off, 0 of 57 with it on. All five were
user-agent related. Every other commonly-cited leak — plugins, mimeTypes,
languages, WebGL vendor/renderer, permissions consistency, window.chrome,
screen dimensions — already passed before any change, on this host. No
page-world JS shims were added: patching signals that already pass is how
you manufacture a new tell.

TLS/JA3 was never a gap. grip drives real Chromium, so the handshake is
Chromium's own.

### Still true

`navigator.userAgentData` is left undefined under UA override rather than
fabricated. A page that detects the DevTools session itself is below
anything an injected script can reach — unfixable for any CDP-based tool.
IP reputation remains an egress problem. Challenge solve rates outside
these synthetic fixtures remain unmeasured, and Cloudflare's public test
sitekeys short-circuit the real widget flow, so production Turnstile's
click path is still untested here.

## [0.8.0] - 2026-08-12

Three audits of the agent-facing surface (ergonomics, browser capability
coverage, robustness), then the fixes. Most of these are defects an
autonomous agent hits and a human driver routes around.

### Security

- **Typed passwords no longer reach snapshot text, the model, or trace
  output.** `gripOwnText` fell through to `el.value` for password inputs.
  The value-capture path and the accessible-text path now share one
  exclusion set, so the two cannot drift apart.
- **Page-authored element handles can no longer collide with grip's.**
  A page could pre-author `data-grip-h` to shadow a live handle or break
  selector resolution; handles are only trusted if grip minted them this
  session, and selectors go through `CSS.escape`.
- **Downloads landing outside the configured directory are dropped.**

### Fixed — actions that reported success while doing nothing

- **`click()` returned ok on disabled, off-screen and overlay-covered
  elements.** It now hit-tests at the element centre and names the
  occluding element when something is in the way.
- **`type()` bypassed React/Vue value trackers** (raw `el.value` assignment,
  no key events, so typeahead never fired) and still reported success. It
  now uses the native value setter, brackets the write with key events, and
  verifies the value took.
- **Every action snapshotted before the page settled**, so a click that
  navigated returned the pre-click page and the agent clicked again.
- **`CONTENT` was truncated at 2000 characters with no marker**, so the
  agent believed it had read the whole page.
- **`page_error` and `prompt_injection` were computed and then dropped** in
  rendering: an agent blocked by an anti-bot wall or auth wall was told
  nothing at all.

### Fixed — wrong element, wrong conclusion

- **`click("Save")` could hit "Save draft".** Exact match now wins outright;
  genuine ambiguity raises `AMBIGUOUS_TARGET` listing the candidates instead
  of silently guessing.
- **A stale ref from a previous document silently resolved to a different
  element.** Refs from a superseded snapshot are now rejected with a
  re-snapshot hint.
- **Failed navigations returned as success.** `Page.navigate`'s `errorText`
  was ignored and the load timeout was swallowed, so DNS failures and
  connection refusals surfaced as a loaded page with status 0.
- **A browser crash was re-classified by string match into
  `ELEMENT_NOT_FOUND`**, looping the agent straight back into a dead
  connection. Typed errors are no longer re-classified.

### Added — state and content agents could not see

- **Element state in the snapshot**: `disabled`, `required`, `checked`,
  `selected` and `value` (password values excluded). Verifying that a box
  is ticked or a submit button is enabled is most of task verification.
- **Inputs labelled only by sibling text are now addressable by label**,
  via an inference chain (label-for/wrapping label, `aria-label`,
  placeholder, title, sibling text, humanized name/id).
- **Scroll position and page height**, plus `scroll()` targeting the
  nearest scrollable ancestor rather than only the window, so inner panes,
  virtual lists and infinite scroll can be reached.
- **Closed shadow roots**, via an `attachShadow` patch installed before
  navigation. They were previously invisible with no signal.
- **iframes** surfaced as rows (no cross-frame traversal yet), **canvas**
  rects and **labelled SVG**, and **comboboxes** with their options.

### Added — capabilities

- **JavaScript dialogs are handled by policy.** Nothing subscribed to
  `Page.javascriptDialogOpening`, so an `alert()`/`confirm()` froze the tab
  until timeout.
- **`wait_for()`** for a text/ref condition, and same-document navigation
  now invalidates the cached snapshot, so `pushState` no longer leaves a
  stale one behind.
- **`hover()`**, for menus that only open on pointer events.
- **`select()` falls back to open, re-snapshot, pick** for non-native
  comboboxes instead of failing outright.
- **Conservative cookie-banner dismissal**, once per navigation.
- **File-chooser interception**, for drop zones that create the input on
  click, and **popup adoption** for OAuth flows.
- **Viewport and device emulation**, and **permission control** with
  notifications and geolocation denied by default so a prompt cannot stall
  a task.

### Fixed — MCP

- **The server died on every tool call when an LLM SDK was not installed.**
  The adapter was resolved eagerly at browser construction, so `open` and
  `click` — which need no model — failed with an `ImportError` on any host
  that sets provider keys without grip's optional extras. It is now
  resolved lazily, only for the `run` tool.
- **`press`, `upload`, `links`, `popups_blocked`, `wait_for`, `hover` and
  `scroll` exposed**; several existed in the Python API but not over MCP.
- **Error recovery hints now reach the client** instead of being dropped at
  the MCP boundary.
- **`screenshot` returns an image block** rather than raw base64 as tool
  text.
- **Overlapping tool calls could act on the wrong tab**; calls are
  serialized.

### Fixed — robustness

- **The Chrome process and temp profile leaked whenever `kill()` timed
  out**, and on any teardown path that was not an explicit `close()`.
- **CDP commands had a fixed 30s timeout with no override.**
- **Crashes and socket drops surfaced as a generic `ConnectionError`**;
  both now map to a typed `BROWSER_CRASHED`.
- **`Fetch.enable` paused every subresource** to enforce a policy that only
  concerns navigations.
- **The trace grew unbounded** on a long-lived server.

### Still not done

Cross-origin iframe traversal (iframes are surfaced, not entered), TLS/JA3
fingerprint parity (below the DevTools Protocol, unreachable from a Python
client), and challenge solve rates remain unmeasured. `enable_downloads` is
deliberately not exposed over MCP: it would let a client create a directory
at an arbitrary server-side path.

## [0.7.0] - 2026-08-12

### Added

- **Non-semantic clickable element discovery.** Elements with a JS click
  listener but no interactive tag or ARIA role (e.g. a `<div>` with
  `addEventListener('click')`) are now found and clickable by description.
  Detection uses CDP `DOMDebugger.getEventListeners`, bounded by a cheap
  scoring pass (`PRE_RANK_LIMIT=150`) with listener probes only on survivors
  (`MAX_LISTENER_PROBE_NODES=40`), issued concurrently. Measured snapshot
  latency cost: Wikipedia 8.5ms → 10.7ms, Hacker News 9.1ms → 12.5ms, no
  token-count change on pages without such elements.
- **`allow_popups` on `NavigationPolicy`** (default `False` — existing secure
  behaviour unchanged). Opting in disables popup blocking; the popup's CDP
  target has no Fetch interception, so `NavigationPolicy` is not enforced
  inside it.

### Changed

- **Popup blocking is now an explicit `NavigationPolicy` option, not an
  unreviewed side effect of v0.6.0.** `window.open()`/`target="_blank"` still
  fails under the default policy — that has not changed — but it is now a
  documented choice (`NavigationPolicy(allow_popups=True)` / `Browser(...,
  allow_popups=True)`) rather than a silent one.
- A blocked popup is no longer silent. It now logs a `WARNING` naming the URL
  and the flag, is counted on `Page.popups_blocked`, and each block is
  recorded as a `"popup_blocked"` entry in `Page`'s `Trace`.

### Known limitations

- Click listeners attached to an ancestor (event delegation) are not
  detected; `getEventListeners` at the node cannot see them.
- `click_at` remains unregistered as an agent tool by design — it takes
  coordinates, which a model without vision cannot usefully produce.

## [0.6.0] - 2026-08-10

### Security

- **`NavigationPolicy` was enforced only in `Browser.open()`.** `Page.goto()`
  had no check, and redirects were never re-checked, so `allow_private=False`
  was bypassable. It is now enforced via CDP Fetch interception at
  `RequestStage.Request` — a refused request fails before Chrome resolves DNS
  or opens a connection — and is armed for the page lifetime rather than
  re-applied per navigation.
- **The private-address block missed IPv4 spellings Chrome accepts but
  Python's `ipaddress` rejects:** `2130706433`, `0177.0.0.1`, `0x7f000001`,
  `127.1`. All are now canonicalized before the check.
- **Popup targets (`window.open`) are closed on attach under a restrictive
  policy,** since a new CDP target carries none of the parent's interception.
- Known limits, stated rather than hidden: WebSocket handshakes are not
  intercepted (CDP's Fetch domain does not cover them); DNS rebinding remains
  out of scope.

### Changed — breaking

- `window.open()` now fails under a restrictive policy, which is the default.
- Session file format changed to `{"cookies": [...], "origins": {...}}`. Old
  bare-list (cookie-only) files still load.

### Added

- `grip` CLI: `open`, `snapshot`, `read`, `screenshot`, `run`, `doctor`.
- File upload/download: `Page.upload()`, `Page.enable_downloads()`,
  `Page.wait_for_download()`.
- localStorage in `save_session`/`load_session` (was cookies-only).
- `Browser.pages` / `Browser.get_page()`; MCP `list_tabs`/`switch_tab`/`close_tab`.
- Gemini adapter; `base_url` on the OpenAI adapter for Ollama/vLLM/LM
  Studio/OpenRouter; `adapter_from_env()`.
- MCP: `goto`, `screenshot`, `run` tools (5 -> 8), install docs at `docs/mcp.md`.

### Fixed

- The MCP server never closed the `Browser` — the clean stdio-exit path
  stranded Chrome and its profile dir.
- The snapshot/delta protocol was implemented twice against private page
  state; now one `Page.payload()`.
- `enable_downloads()` registered its listener after enabling events, so a
  download completing in that window was dropped and `wait_for_download()`
  timed out with the file already on disk.
- Adapter selection was duplicated in `cli.py` and `mcp/server.py`, so `grip
  run` and the MCP run tool could not reach Gemini or OpenAI-compatible
  endpoints.
- `assert self._llm is not None` in `Browser.run()` vanished under `python -O`.
- CI: stealth tests pinned Chrome-build-dependent booleans; the workflow
  claimed offline while seven tests hit live URLs.

## [0.5.1] - 2026-08-10

### Fixed

- **A delta could cost more than the page it replaced.** On a click-driven
  navigation where the reported URL trailed the document, `build_delta` did not
  see a URL change, diffed two unrelated pages, and emitted a wholesale
  replacement — 5,701 tokens where the full snapshot was 2,963, in 6 of 22 runs.
  Two independent guards now bound it: a delta that is not meaningfully smaller
  than the snapshot loses to it at the point the payload is chosen, and a
  restamped-document check compares the elements behind shared handles, since a
  handle stamped per document names a different element after a restart. Found
  by grip's own benchmark, not by a user.
- **A launch failure said only "timed out".** Chrome's stderr went to
  `/dev/null`, so a failed launch could not say why. The error now carries the
  process state, exit code, port-file path and the tail of Chrome's own
  complaint, and distinguishes a Chrome that died before writing the port from
  one still running when the deadline passed. The deadline is configurable via
  `GRIP_CHROME_LAUNCH_TIMEOUT`, because ten seconds is tight for a cold Chrome
  on a loaded CI runner.
- **A reused profile kept the previous run's `DevToolsActivePort`,** so
  `_read_port` could return a dead port instead of waiting for the one Chrome
  was about to write — a defect in the persistent-profile feature added in
  0.5.0.
- **`find_chrome()` trusted `CHROME_EXECUTABLE` without checking it existed,**
  so a stale value produced an opaque `Popen` failure instead of the clear
  "Chrome/Chromium not found" error.

### Changed — measured claims corrected

0.5.0 shipped with numbers that were more confident than the measurement
supported. All of them came from a synthetic single-page loop or a run whose
data was never saved. Re-measured against four live sites and eight real pages:

- The snapshot delta was described as a **75% per-turn saving**. Its median
  per-turn contribution across a mixed run is **1.0x**, because `build_delta`
  returns `None` on a URL change and a realistic agent run is mostly navigation.
  Where it does fire — inside one document, filling a form, driving an SPA — it
  is a **9.1x median** saving, range 0.5x–175x.
- The honest end-to-end figure is **~18x fewer prompt tokens over a six-turn
  run** (16.9x–18.4x across repeat runs), and it is dominated by compression,
  not by the delta.
- Compression against raw HTML was stated as **19x**. That figure came from a
  run whose data no longer exists. Re-measured on the same corpus by the same
  statistic: **16.0x**, median of per-page ratios, range 3.3x–68.4x.
- Competitor cells that read "not measured" are measured: grip 1,998 tokens
  median against Playwright MCP 11,597, Puppeteer's accessibility tree 27,489
  and `page.content()` 58,280. grip is smallest on 8 of 8 pages.

Every figure now carries its statistic, its date and its range. Full method in
`benchmarks/RESULTS_AB.md` and `benchmarks/RESULTS_COMPETITORS.md`.

### Changed — tests

- Two tests passed only on a machine with no Chrome in `PATH`, which is why the
  0.5.0 branch stayed green locally while CI failed. One mocked `subprocess.run`
  after the code had moved to `shutil.which`; the other asserted something
  vacuously true where `find_chrome()` returns `None`. The lint job also linted
  a dependency set users never install, so five decorator errors only appeared
  on CI.

## [0.5.0] - 2026-08-10

### Correction to this entry

The delta figure below — "628 tokens per turn becomes 42, a 75% cut" — is a
single-page best case reported as if it were typical. It came from a synthetic
five-turn loop that never navigated away from one document, which is the one
condition under which the delta always fires. The original wording is left in
place because 0.5.0 is published; this note corrects the record rather than
erasing it.

Measured since on four live sites, six real turns each (medians of per-scenario
ratios, tiktoken `cl100k_base`):

- compression, grip snapshot vs raw HTML, per turn: **11.3x** (2.9x–22.0x)
- delta vs full snapshot every turn, per turn: **1.0x** (1.0x–8.8x) —
  `build_delta` returns `None` on a URL change, so navigation turns send a full
  snapshot by design
- pruning, cumulative: **1.4x** (1.0x–2.2x)
- end to end, raw HTML vs grip delta + pruning, cumulative: **17.8x**
  (4.6x–41.8x per scenario; 16.9x–18.4x across repeat runs)

On the 8 turns of 24 where a delta could fire, the saving was **9.1x** median,
range **0.5x–175.0x**. Method, per-scenario tables and caveats:
[`benchmarks/RESULTS_AB.md`](benchmarks/RESULTS_AB.md).

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
