# Observation payload size: grip vs Playwright MCP vs Puppeteer

Date: 2026-08-10. Wall time 225.8s. Encoder: **tiktoken `cl100k_base`** for every
column without exception.

```
.venv/bin/python benchmarks/bench_competitors.py
```

## What this measures — and what it does not

This measures **one thing**: the number of tokens in the page observation each
tool hands a model. That is it.

It says **nothing** about task success, latency, reliability, cross-browser
support, ecosystem size, documentation, or maturity. A smaller payload is not a
better tool; it is a smaller payload. If your agent fails the task, the token
count of its failure is irrelevant.

**Playwright and Puppeteer are general-purpose browser automation frameworks
with far broader scope than grip.** They drive human-facing E2E test suites
across Chromium, Firefox and WebKit, with years of ecosystem behind them. grip
does one narrow thing: produce the smallest useful view of a page for an LLM.
A reader choosing between these tools on the strength of this table alone would
be choosing badly. This table is one axis of many, and it is the axis grip was
built to win.

**The comparison is like-for-like on interaction refs.** Playwright MCP's
snapshot embeds refs (`[ref=e3]`) that the model uses to target subsequent
actions — they are part of the payload and they are counted here. grip's
snapshot embeds its own refs in the same way (`[btn:e3]`, see
`grip/compression/summarizer.py`), and those are counted too. Neither side is a
stripped-down payload measured against a rich one.

## Versions

| | |
|---|---|
| grip | 0.5.0 |
| @playwright/mcp | 0.0.78 |
| playwright | 1.62.1 |
| puppeteer | 25.4.0 |
| tiktoken | 0.13.0 |
| python | 3.14.5 |
| node | v25.8.1 |

Pages: the same 8 real pages from `evaluation/corpus.py` that grip's existing
19x-vs-raw-HTML claim uses. The Playwright MCP arm counts the `browser_snapshot`
tool result, taken after `browser_navigate`, over real stdio MCP (initialize /
tools/list / tools/call) — preamble included.

## Per-page tokens

| page | raw_html | grip | playwright_mcp | puppeteer_html | puppeteer_a11y |
|---|---:|---:|---:|---:|---:|
| wikipedia | 459,193 | 19,946 | 144,927 | 446,049 | 371,872 |
| github | 172,050 | 2,517 | 11,848 | 170,700 | 48,810 |
| react.dev | 103,848 | 1,550 | 11,346 | 103,181 | 52,194 |
| hacker news | 13,701 | 3,540 | 13,773 | 11,865 | 35,788 |
| bbc | 110,383 | 2,426 | 12,832 | 109,243 | 19,189 |
| python docs | 8,818 | 1,077 | 5,699 | 8,430 | 14,047 |
| arxiv | 13,976 | 1,570 | 5,293 | 13,378 | 13,102 |
| example.com | 167 | 50 | 123 | 163 | 223 |

Every arm produced a number on all 8 pages (n=8/8). No cell is estimated,
extrapolated, or read off documentation.

## Medians

| arm | median | min | max |
|---|---:|---:|---:|
| raw_html | 58,912 | 167 | 459,193 |
| grip | **1,998** | 50 | 19,946 |
| playwright_mcp | 11,597 | 123 | 144,927 |
| puppeteer_html | 58,279.5 | 163 | 446,049 |
| puppeteer_a11y | 27,488.5 | 223 | 371,872 |

With n=8 the median is the mean of the 4th and 5th values, so two of these land
on a half token. They are reported as computed rather than rounded to look tidy.

The spread matters more than the median here. Every arm covers three to four
orders of magnitude across these 8 pages, because the pages do. Quoting any
single median as "what this tool costs" is quoting a number that is wrong for
most individual pages by a large factor in one direction or the other.

## Per-page ratios

grip is the smallest payload on all 8 of 8 pages. How much smallest varies
enormously, so here is the ratio on each page rather than a single headline:

| page | grip tokens | vs raw_html | vs playwright_mcp | vs puppeteer_html | vs puppeteer_a11y |
|---|---:|---:|---:|---:|---:|
| wikipedia | 19,946 | 23.0x | 7.3x | 22.4x | 18.6x |
| github | 2,517 | 68.4x | 4.7x | 67.8x | 19.4x |
| react.dev | 1,550 | 67.0x | 7.3x | 66.6x | 33.7x |
| hacker news | 3,540 | 3.9x | 3.9x | 3.4x | 10.1x |
| bbc | 2,426 | 45.5x | 5.3x | 45.0x | 7.9x |
| python docs | 1,077 | 8.2x | 5.3x | 7.8x | 13.0x |
| arxiv | 1,570 | 8.9x | 3.4x | 8.5x | 8.3x |
| example.com | 50 | 3.3x | 2.5x | 3.3x | 4.5x |

Median of the per-page ratios:

| grip vs | median ratio | range |
|---|---:|---|
| raw_html | 16.0x | 3.3x – 68.4x |
| playwright_mcp | 5.0x | 2.5x – 7.3x |
| puppeteer_html | 15.4x | 3.3x – 67.8x |
| puppeteer_a11y | 11.6x | 4.5x – 33.7x |

The median of the ratios is not the ratio of the medians (that would give 5.8x
against Playwright MCP rather than 5.0x), because the pages where grip wins
biggest are not the pages sitting at the median of either column. The per-page
ratios above are the honest form; the ratio-of-medians is the flattering one.

Against Playwright MCP the advantage is the narrowest and the most stable:
between 2.5x and 7.3x, never more. Both are accessibility-tree approaches, so
they are compressing the same thing in the same direction and the gap is a
matter of degree, not of kind. Against raw HTML and `page.content()` the
advantage is both larger and far more erratic.

## The Hacker News row

On Hacker News, **Playwright MCP's snapshot (13,773 tokens) is larger than the
raw HTML it describes (13,701 tokens)** — a 1.005x expansion, not a reduction.

This is the most interesting row in the table and it should not be read past.
An accessibility tree is **not** automatically smaller than the document. Hacker
News is a page that is almost entirely links with very little markup around
them: the HTML is thin, so there is little markup to strip, and each link still
has to be described in the tree with a role, a name and a ref. On that shape of
page the structural overhead of describing the document costs more than the
document.

This cuts against the simple "accessibility tree = compression" story — which is
a story **grip also benefits from**, and grip's own Hacker News numbers are its
weakest on the board (3.9x vs raw HTML, its joint-lowest, and 3.9x vs Playwright
MCP). The mechanism that makes these tools cheap is stripping markup. When there
is little markup to strip, the mechanism has little to do, and it can go
negative. Nothing here guarantees a reduction on a page you have not measured.

## A caution about measuring nothing

The **first run of this benchmark reported a constant 32 tokens for Playwright
MCP on every page.** That looked like a spectacular result. It was not a result
at all: the Playwright MCP browser was not installed, `browser_snapshot` was
returning an error string, and the harness was tokenizing the error and
recording it as a snapshot.

A constant value across 8 wildly different pages should have been immediately
suspicious, and it is exactly the kind of failure that produces a publishable
number out of a tool that never ran. It is recorded here because a benchmark you
can trust is one that tells you how it was nearly wrong. The harness now refuses
to emit a number for an arm it could not run: it emits `unmeasured` plus the
error text instead.

If you reproduce this and see suspiciously round, suspiciously constant, or
suspiciously small values in any column, assume the tool did not run before you
assume it won.

## Reproducing

```
.venv/bin/python benchmarks/bench_competitors.py [--out results.json]
```

Prerequisites:

- **Playwright MCP browser must be installed**, or the arm silently measures
  nothing (see above):
  ```
  npx @playwright/mcp install-browser chrome-for-testing
  ```
- **Puppeteer** was installed with `PUPPETEER_SKIP_DOWNLOAD` set, pointing at an
  already-installed Chrome rather than downloading its own.
- Node and npm on `PATH` (measured on node v25.8.1).
- Network access: all 8 pages are live public sites, fetched at run time. There
  are no fixtures and no cached state.

Because the pages are live and each arm drives its own browser, the three
browsers see each page at three slightly different moments. Expect run-to-run
movement on the news-shaped pages (BBC, Hacker News) in particular. Numbers here
are a single run on the date above, not an average.
