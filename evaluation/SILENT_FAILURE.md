# Silent-failure evaluation

**Result: mixed, and weaker than the hypothesis as originally framed. grip's explicit
`page_error` field never fired on any of the 7 failure pages tested — 0/7. But held to
the same content-length bar static's output is judged by, grip's boilerplate-free
`read()` output correctly falls below it on 2/7 pages where static's padded output
clears it: a consent wall (LinkedIn) and a soft 404 (angular.dev). The other 5/7 failure
pages were "loud" — static's own output was short enough that a naive length gate would
already reject it, so grip added nothing there. Zero false positives on 5 control
pages.**

Run it yourself: `.venv/bin/python -m evaluation.run_silent_failure`
Raw data: [`silent_failure_results.json`](silent_failure_results.json).
Corpus: [`silent_failure_corpus.py`](silent_failure_corpus.py).

## What was being tested

The reach evaluation ([`README.md`](README.md)) falsified the claim that a browser
retrieves content static fetch cannot — the gap was zero across 33 URLs. This tests the
second surviving hypothesis: pages that fail while still returning HTTP 200 — consent
walls, anti-bot interstitials, JS-required shells, soft 404s — where a static fetcher
has no signal anything went wrong and hands a retrieval pipeline plausible junk, while
grip is supposed to know via `page_error` or an empty `read()`.

## Method

Both arms fetch the same URL. Static fetch reuses `static_fetch()` from
`run_reach.py` unmodified. grip calls `page.snapshot()` (for `page_error`) and
`page.read()` (for block count and character count).

Static's output is scored against a **naive quality gate**: HTTP 200 and more than 500
characters of extracted text — the kind of check a pipeline that isn't specifically
built to detect blocking would apply. grip is judged by the *same* 500-character bar,
plus whether `page_error` was set.

**Corpus**: 7 pages picked to fail while returning 200 (consent wall, JS-required
shell, soft 404, anti-bot page) plus 5 genuinely good control pages, so the benchmark
can produce false positives. `expect_failure` ground truth is set by hand per URL,
checked against the actual extracted text (shown in the results table below), not
inferred from the category label.

## Results

| category | n | true positive | self-reported (not silent) | missed | false positive |
|---|---|---|---|---|---|
| consent_wall | 2 | 1 | 1 | 0 | — |
| js_shell | 2 | 0 | 2 | 0 | — |
| soft_404 | 2 | 1 | 1 | 0 | — |
| anti_bot | 1 | 0 | 1 | 0 | — |
| control | 5 | — | — | — | 0 |
| **total (failure pages, n=7)** | | **2** | **5** | **0** | |
| **total (control pages, n=5)** | | | | | **0** |

- **True positive** — static's output passed the naive gate (silently accepted as
  good), grip's did not (page_error, or `read()` below the same 500-char bar).
- **Self-reported** — static's own output also failed the naive gate. Not silent: any
  pipeline checking output length, without knowing anything about grip, would already
  reject it.
- **Missed** — neither arm caught it. Did not occur.
- **False positive** — grip flagged a control page that was actually fine. Did not
  occur, on 5 pages.

### The two true positives, in detail

**LinkedIn** (`linkedin.com/pulse/topics/home/`) — static fetch returns 3,412
characters, comfortably clearing the naive gate. Inspecting the actual string: it is
LinkedIn's cookie-consent boilerplate ("LinkedIn respects your privacy... Cookie
Policy..."), not article content. grip's `read()` returns 69 characters: "What topics do
you want to explore? Editor's Picks Topic Categories" — thin, but it is the real page,
correctly stripped of the consent chrome. `page_error` was **not** set; grip's
classifier only pattern-matches captcha/block/rate-limit/login-wall text in the page
title, and none of those patterns matched here. The signal that caught this was length,
not the error classifier.

**angular.dev soft 404** (`angular.dev/some-totally-fake-page-xyz`) — static fetch
returns 2,114 characters of the site's real homepage content ("Home • Angular... The
framework for building scalable web apps...") with no indication anywhere in the text
that the requested path doesn't exist, because the server's client-side router serves
the app shell with HTTP 200 for any path. grip's `read()`, after running the client
router's JS, returns 131 characters: "Page Not Found / We couldn't find what you were
looking for." — the router actually resolved the non-route and rendered its own 404
UI. Again, `page_error` was **not** set (the title "Page not found • Angular" doesn't
match the classifier's block/captcha/auth patterns), and again the signal was length.

### What did not confirm the hypothesis

`snapshot.page_error` was `None` on **all 7** failure pages, including Google search
(served a stripped consent-error interstitial, both arms got ~0 content) and Reddit
(anti-bot page, both arms got ~0 content). grip's page-state classifier
(`grip/errors/classifier.py`) checks page **title** against captcha/"just a
moment"/login-wall word lists — it has no path that recognizes a consent banner, a bare
app shell, or a client-rendered 404 message, all of which had ordinary titles ("Top
Content on LinkedIn", "Page not found • Angular", "Telegram", "Excalidraw Whiteboard").
The mechanism the hypothesis named as the differentiator (`page_error`) is not, in this
corpus, actually doing the work.

What *is* doing the work, on the 2/7 where anything did: grip's `read()` strips
navigation/chrome/boilerplate that static fetch keeps, so a page with real but sparse
content falls below a fixed length bar that static's padding clears. That is a real,
measurable effect, but it is length-based content extraction quality, not the
explicit "I detected a failure" signal the hypothesis originally described.

### A methodology fix worth naming

The first pass of this script held grip's output to a much laxer emptiness threshold
(50 characters) than static's (500), inherited without justification when the script
was written. Under that asymmetric threshold, the true-positive count was 0/7, and the
two pages above were coded as "missed" because grip's 69 and 131 characters didn't
trip the 50-character bar even though they were well short of what a length-based
quality gate would accept. Holding both arms to the identical 500-character line raised
the count to 2/7. This is reported explicitly because using a different bar for each
arm without cause is exactly the kind of asymmetry that has inflated results in this
project before (see the reach evaluation's whitespace and entity-decoding bugs) — the
fix here goes the other direction, making the comparison *fairer*, not more flattering,
and it was checked by inspecting the actual LinkedIn/angular.dev strings above before
being trusted.

## Honest conclusion

The hypothesis, as stated — "grip reports `page_error` where static silently
succeeds" — does not hold on this corpus. `page_error` fired zero times. A narrower,
still-real version holds weakly: **on 2 of 7 tested silent-failure pages, grip's
extracted content was short enough to fail the same quality bar that static's padded
output cleared.** On the other 5, static's own output was already short enough to
self-report the failure, so grip added nothing a naive length check wouldn't have
caught alone. Zero false positives on 5 control pages, which is the one clean result:
grip did not wrongly flag any genuinely good page.

This is a real but modest and mechanism-mismatched effect, not the clean differentiator
the hypothesis predicted. If this is going to be a claim, it should be stated as "grip's
extraction strips boilerplate that pads out failed pages, occasionally revealing
thinness a naive gate would otherwise miss" — not "grip detects and reports blocked
pages," because the field built for exactly that purpose did not fire once.

## Limitations

- **n=7 failure pages, n=5 controls, one run, one residential IP.** Consent-wall and
  anti-bot behaviour is IP- and region-dependent; Google in particular varies by
  locale and account state.
- **The naive gate (200 + >500 chars) is one specific, simple heuristic**, chosen
  because it is what an unsophisticated pipeline would plausibly implement. A more
  sophisticated static pipeline (boilerplate removal, readability scoring) might catch
  some of these pages too — this evaluation does not test that, and a fairer
  static-arm extractor would likely close part of the 2/7 gap.
- **`grip/errors/classifier.py`'s title-pattern approach is the actual bottleneck**
  found here: it is not designed to catch consent banners or "not found" UI text, and
  extending it was out of scope for this evaluation (evaluation/ only).
- **The two true positives share a mechanism** (length-based, not error-detection
  based) — this is one effect observed twice, not two independent confirmations.
