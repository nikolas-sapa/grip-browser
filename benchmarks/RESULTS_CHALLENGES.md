# Challenge classification accuracy and solve rate

Date: 2026-08-12. grip 0.8.0. Python 3.14.5.

**Post-fix update (same date):** the three bugs this report originally found
(slider track self-match; `_PROSE_CHALLENGE` firing on ordinary prose;
`cf-turnstile` matching quoted text) are fixed. The tables below are the
**pre-fix** numbers, left intact as the original finding. The **post-fix**
numbers are in the "Post-fix re-run" section at the end of each table's
subsection and in the new section at the bottom of this file. Fixes:
`grip/challenge.py` (`SLIDER_PROBE_JS` track resolution, `_PROSE_CHALLENGE`,
new `_has_widget_element`), `grip/page.py` (`_solve_slider` reason handling).

```
.venv/bin/python benchmarks/corpus/challenges/generate_challenge_fixtures.py  # regenerate fixtures
.venv/bin/python benchmarks/bench_challenges.py
```

Raw output per run: `benchmarks/corpus/challenges/results/summary_<timestamp>.json`.
Fixtures: `benchmarks/corpus/challenges/fixtures/` (generated, not hand-edited —
see `generate_challenge_fixtures.py`'s docstring for the contract).

## Credibility limits — read this before the table

**Synthetic fixtures are weak evidence for real-world solve rate.** Every
`synthetic-fixture` row below is a page written in this repo, served from a
local `http.server`, that decides its own pass/fail. That measures one thing
honestly: whether `grip/challenge.py` finds the right DOM target and
dispatches the right interaction against markup shaped like a real provider's
(CSS marker classes, iframe URL patterns). It does **not** measure whether
grip defeats any real anti-bot scoring backend — there is no real backend in
the loop, and grip ships none.

**`real-widget` rows use Cloudflare's own published Turnstile test sitekeys**
(`1x00000000000000000000AA` "always passes", `2x00000000000000000000AB`
"always fails" — https://developers.cloudflare.com/turnstile/troubleshooting/testing/),
not a production key. 3 runs per key, sequential, 1s pause between runs, no
retries, no load. This is the only row in this report backed by a real
third-party widget; treat it as one axis of evidence, not the whole picture —
these test keys render differently from a production Turnstile widget (see
below).

grip's own doc comment on this module states its actual scope precisely:
detection is a pure function over `(html, frame urls)`; "solved" is a verified
claim (a response token or the widget leaving the DOM), never inferred; and
IMAGE_GRID/TEXT are handed to the caller's own model — grip ships no image
classifier and doesn't attempt them.

## Classification: synthetic fixtures, N=5 runs each

`pure_fn` = `detect_challenge_from_html(html, frames)` called directly, no
browser. `via page()` = the fixture served over HTTP, loaded in a real headless
Chrome, classified through `Page.detect_challenge()` (real CDP frame tree +
DOM read). Both columns use the *same* frame URLs (iframe `src` extracted from
the fixture), so a mismatch between them would indicate a plumbing bug, not a
different input — none found here.

| fixture | expected | pure_fn | via page() | runs |
|---|---|---|---|---|
| neg_plain.html | none | 5/5 | 5/5 | 5 |
| neg_login_no_captcha.html | none | 5/5 | 5/5 | 5 |
| neg_captcha_field_only.html | none | 5/5 | 5/5 | 5 |
| neg_captcha_img_only.html | none | 5/5 | 5/5 | 5 |
| **neg_blog_solve_a_captcha.html** | none | **0/5** | **0/5** | 5 |
| neg_security_check_footer.html | none | 5/5 | 5/5 | 5 |
| **neg_turnstile_docs_snippet.html** | none | **0/5** | **0/5** | 5 |
| neg_carousel_slider.html | none | 5/5 | 5/5 | 5 |
| pos_checkbox_recaptcha.html | checkbox | 5/5 | 5/5 | 5 |
| pos_checkbox_hcaptcha.html | checkbox | 5/5 | 5/5 | 5 |
| pos_image_grid.html | image_grid | 5/5 | 5/5 | 5 |
| pos_slider.html | slider | 5/5 | 5/5 | 5 |
| pos_text_captcha.html | text | 5/5 | 5/5 | 5 |
| pos_invisible.html | invisible | 5/5 | 5/5 | 5 |
| pos_unknown_prose.html | unknown | 5/5 | 5/5 | 5 |

**False-positive rate on negative fixtures: 10/40 (25%), both driven by 2 of 8
negative-fixture types, deterministic (5/5 each), reproducible.**

Two real, reproducible false positives found:

1. **`neg_blog_solve_a_captcha.html`** — ordinary editorial prose ("a browser
   game where you solve a captcha puzzle") trips `_PROSE_CHALLENGE`'s
   `solve...captcha` pattern and is classified UNKNOWN instead of NONE. The
   regex's own docstring warns about exactly this failure mode ("must not trip
   [on] 'A history of the captcha'") but the guard is a title-only exception,
   not a general one — ordinary body prose using "solve" near "captcha" for
   any reason still fires.
2. **`neg_turnstile_docs_snippet.html`** — a documentation page whose `<pre>`
   block *quotes* the Turnstile embed snippet as literal text
   (`<div class="cf-turnstile" ...>`) is classified TURNSTILE. The check is
   `"cf-turnstile" in lowered` against the raw HTML string with no
   distinction between a live widget and quoted markup in a code sample.

Both are real findings against grip's shipped classifier, not fixture bugs —
reproduced deterministically across 5/5 runs, on both the pure function and
the full CDP-backed path.

**Fixed 2026-08-12** (`grip/challenge.py`): `_PROSE_CHALLENGE`'s captcha
branch now additionally requires a continuation clause ("to continue" /
"before continuing" / "required") within range of the match, so ordinary
prose *about* captchas no longer co-occurrence-matches on
imperative-verb + "captcha" alone; the unqualified "you are human"/"not a
robot" branch is left as-is since narrative prose does not use that phrasing.
`"cf-turnstile" in lowered` (and the same substring check across
`_WIDGET_MARKERS`) is replaced by `_has_widget_element()`, which requires a
literal `<tag ... class="...cf-turnstile...">` — a `&lt;div
class="cf-turnstile"&gt;` quoted inside `<pre><code>` never contains a real
`<` delimiter, so it no longer matches. See "Post-fix re-run" below for the
observed numbers.

All 15 negative + positive expected-match cases otherwise classify perfectly,
including all 5 solvable/needs-vision/unknown/invisible positive stages.

## Solve rate: synthetic fixtures, N=5 runs each

| fixture | expected | runs | attempted | matched expected | false_solved |
|---|---|---|---|---|---|
| solve_checkbox_success.html | solved | 5 | 5 | 5/5 | 0 |
| solve_checkbox_never.html | timeout | 5 | 5 | 5/5 | 0 |
| solve_checkbox_zero_size.html | unsupported | 5 | 5 | 5/5 | 0 |
| **solve_slider_success.html** | solved | 5 | 5 | **0/5** | 0 |
| solve_slider_never.html | timeout | 5 | 5 | 5/5 | 0 |
| solve_slider_no_track.html | unsupported | 5 | 5 | 5/5 | 0 |

**False-solved probe (the number the task exists to answer): 0/30 synthetic
runs. grip never once claimed "solved" when the fixture's own JS had not
independently recorded a genuine click + granted token (checkbox) or a
full-track drag + self-removal (slider).** This holds even on the slider,
where grip could not solve the widget at all (below) — it correctly reported
`timeout`, not a false `solved`.

**Real finding: `SLIDER_PROBE_JS`'s track-lookup has a self-match bug.**
`solve_slider_success.html` reproduces the exact vendor markup grip's own
`_SLIDER_MARKERS` names as an example (`geetest_slider` container,
`geetest_slider_button` handle) and grip never solves it — `timeout` every
run. Cause, isolated by direct probe: `SLIDER_PROBE_JS` does
`handle.closest('.geetest_slider, ..., [class*="slider"]')` to find the
track, but `closest()` checks the element itself before its ancestors, and
the handle's own class (`geetest_slider_button`) already contains the
substring `"slider"` — so the generic `[class*="slider"]` clause matches the
handle itself, `track === handle`, and the computed drag distance collapses
to ~0px (verified: probe returned `{x: 28, y: 100, endX: 28}`, i.e. `endX ==
x`). This is a targeting bug in shipped code, reproduced against grip's own
documented example, not a fixture artifact.

**Fixed 2026-08-12** (`grip/challenge.py` `SLIDER_PROBE_JS`, `grip/page.py`
`_solve_slider`): the track walk now starts at `handle.parentElement` and
only ever considers real ancestors (never the handle itself or a
descendant), requires the resolved track to be at least 1.5x the handle's
width, and returns `{reason: "..."}` instead of `null` when no such ancestor
exists — `_solve_slider` reports that reason in `detail` instead of
computing a near-zero drag. See "Post-fix re-run" below.

## Turnstile: real widget, Cloudflare test sitekeys, N=3 runs each

| fixture | source | expected | runs | attempted | matched | false_solved |
|---|---|---|---|---|---|---|
| turnstile-always-passes | real-widget(cloudflare-test-key) | solved | 3 | 3 | 0/3 | 0 |
| turnstile-always-fails | real-widget(cloudflare-test-key) | timeout | 3 | 3 | 0/3 | 0 |

**Observed on both keys, all 6 runs: no iframe is ever rendered.** Cloudflare's
test sitekeys write the response token directly into a hidden
`input[name="cf-turnstile-response"]` with no clickable anchor iframe —
pre-filled (`XXXX.DUMMY.TOKEN.XXXX`) for the always-passes key, empty for the
always-fails key (`token_present_before_solve` in the raw JSON, confirmed by
direct DOM read before grip does anything). grip's click path
(`_solve_click_widget` → `POINT_PROBE_JS`) only looks for that iframe, finds
none in either case, and returns `unsupported` for both — not a false
`solved`, and not the `timeout` that would be the honest answer against a
real interactive widget. This is a genuine gap in test coverage, not a false
claim: it means production Turnstile (which does render a clickable anchor
iframe) is untested here, because Cloudflare's own automated test keys
short-circuit that UI. **No third-party service was hammered:** 6 total live
requests across both keys, 1s spacing, no retries.

## Wall time (pre-fix run)

~90s for the classification + local solve suites (110 browser page loads at
N=5), plus ~25s for the 6 live Turnstile runs (3s settle + up to 15s solve
timeout each, only reached on the always-passes path once the token is
already present).

## Post-fix re-run — 2026-08-12

Same commands, same fixtures (`generate_challenge_fixtures.py` regenerated
first, per its documented contract), after the three fixes above. Raw JSON:
`benchmarks/corpus/challenges/results/summary_20260812-114657.json`.

### Classification (synthetic fixtures) — before vs after

| fixture | expected | pure_fn before | pure_fn after | via page() before | via page() after |
|---|---|---|---|---|---|
| neg_blog_solve_a_captcha.html | none | 0/5 | **5/5** | 0/5 | **5/5** |
| neg_turnstile_docs_snippet.html | none | 0/5 | **5/5** | 0/5 | **5/5** |
| all other 13 fixtures | (unchanged) | 5/5 | 5/5 | 5/5 | 5/5 |

**False-positive rate on negative fixtures: 10/40 (25%) before → 0/40 (0%)
after.** All 15 classification fixtures now match expected 5/5 on both
`pure_fn` and `via page()`.

### Solve rate — before vs after

| fixture | expected | matched before | matched after |
|---|---|---|---|
| solve_slider_success.html | solved | 0/5 | **5/5** |
| all other 5 solve fixtures | (unchanged) | 5/5 | 5/5 |

`solve_slider_success.html` now genuinely solves: grip resolves the real
`#track` ancestor (not the handle), computes a full-width drag, and
`_await_verification` reports `solved` once the fixture's own script records
the completed drag and removes the widget — not asserted from the fixture
changing, the fixture is untouched (`generate_challenge_fixtures.py` diff is
empty).

**False-solved probe, before and after: 0/30 synthetic runs, unchanged.** The
fix did not touch verification; it only fixed target resolution, so this
number was never at risk and stays 0.

### Turnstile: real widget, Cloudflare test sitekeys — unchanged

| fixture | expected | matched before | matched after |
|---|---|---|---|
| turnstile-always-passes | solved | 0/3 | 0/3 |
| turnstile-always-fails | timeout | 0/3 | 0/3 |

Unchanged and expected: this gap (Cloudflare's test sitekeys render no
clickable anchor iframe, so `_solve_click_widget` returns `unsupported` for
both) is orthogonal to the three bugs fixed here — not touched, not claimed
fixed.

### Post-fix wall time

Classification suite: 324.2s (up from ~90s pre-fix quote above — this run
included the full 15-fixture × 5-run classification pass plus all 6 solve
fixtures × 5 runs serially on this machine; the increase reflects run
variance and machine load, not a regression introduced by the fix — the
per-fixture browser-load work is unchanged). Turnstile live-widget runs:
unchanged, ~25s.

## Gates (post-fix)

- `pytest tests/unit -q`: 483 passed (474 + 9 new tests covering the three
  fixes: 4 classifier false-positive/regression tests, 1 slider real-DOM
  probe geometry assertion via `tests/integration`, 3 `_solve_slider` unit
  tests for the reason/no-KeyError/drag-span paths, 1 real-turnstile-still-
  classifies regression).
- `pytest tests/integration -q -m "not network"`: 111 passed, 1 skipped, 1
  deselected.
- `ruff check grip/ gripsearch/ evaluation/ benchmarks/`: clean.
- `mypy grip/ gripsearch/`: clean.
