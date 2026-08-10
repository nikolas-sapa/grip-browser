# grip

[![PyPI version](https://img.shields.io/pypi/v/grip-browser?style=flat-square&color=0B0B0D&labelColor=0B0B0D)](https://pypi.org/project/grip-browser/)
[![License: MIT](https://img.shields.io/badge/license-MIT-0B0B0D?style=flat-square&labelColor=0B0B0D)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/grip-browser?style=flat-square&color=0B0B0D&labelColor=0B0B0D)](https://pypi.org/project/grip-browser/)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-0B0B0D?style=flat-square&labelColor=0B0B0D)](CONTRIBUTING.md)
[![CI](https://img.shields.io/github/actions/workflow/status/nikolas-sapa/grip-browser/test.yml?style=flat-square&label=tests&color=0B0B0D&labelColor=0B0B0D)](https://github.com/nikolas-sapa/grip-browser/actions)

**Token-efficient, CDP-native browser SDK for AI agents.**

Built directly on Chrome DevTools Protocol — no Playwright, no Puppeteer, no wrapper overhead.

```
pip install grip-browser
```

---

## What is Grip?

**Grip is a CDP-native browser SDK for AI agents that turns a web page into a ~2,000-token semantic snapshot instead of ~59,000 tokens of raw HTML** (medians over 8 real pages, 2026-08-10). It runs on the Chrome DevTools Protocol directly — no Playwright, no Puppeteer, no wrapper binary.

### Why Grip

Agents don't need the DOM. They need to know what's on the page and what they can act on. Grip sends the model only the interactive elements and visible text — structured, indexed, and fuzzy-matchable.

Measured across 8 real pages (Wikipedia, GitHub, react.dev, BBC, Hacker News, Python docs, arXiv, example.com) on 2026-08-10: **grip's snapshot is a median 16.0x smaller than the page's raw HTML** — that is the median of the per-page ratios, and per page it runs from 3.3x on example.com, which is already tiny, to 68.4x on GitHub. The underlying medians are 58,912 tokens of raw HTML (range 167–459,193) against 1,998 tokens of grip snapshot (range 50–19,946). Per-page tables: [`benchmarks/RESULTS_COMPETITORS.md`](benchmarks/RESULTS_COMPETITORS.md).

The spread is the point: quoting the median alone is wrong for most individual pages by a large factor in one direction or the other.

That 16.0x is against **raw HTML**, which is the right comparison if your agent would otherwise put the DOM in the prompt. Against naively tag-stripped text — what a retrieval API sends a model — the reduction is only about **1.4x**, because most of what grip removes is markup rather than words. That 1.4x is a separate, older measurement: median characters over the 23 pages of the 33-page reach corpus where both arms returned content, range 0.5x–3.7x, and it has not been re-run against the 8-page corpus above. Both numbers are measured; use whichever matches what you would otherwise send. Method and data: [`evaluation/`](evaluation/).

### Grip vs Playwright MCP vs Puppeteer

| | Playwright MCP | Puppeteer | Grip |
|---|:---:|:---:|:---:|
| Tokens per snapshot | 11,597 median | 58,280 median (HTML)<br>27,489 median (a11y tree) | **1,998 median** |
| Built on | Playwright | Chromium binary API | pure CDP |
| Shadow DOM traversal | partial | no | full |
| Fuzzy element match (no selectors) | no | no | yes |
| Typed error recovery | no | no | yes |
| Prompt-injection guard | no | no | yes |

All three token figures are measured on the same 8 real pages with the same encoder
(tiktoken `cl100k_base`), run 2026-08-10. Of these three, grip is the smallest payload
on 8 of 8 pages — a median **5.0x** below Playwright MCP (range 2.5x–7.3x) and **15.4x** below
Puppeteer's `page.content()`. Puppeteer has no single canonical observation, so both
the HTML and accessibility-tree payloads are shown. On Hacker News, Playwright MCP's
snapshot came out *larger* than the raw HTML it describes — an accessibility tree is
not automatically a compression. Per-page tables, ratios and method:
[`benchmarks/RESULTS_COMPETITORS.md`](benchmarks/RESULTS_COMPETITORS.md).

This measures payload size only. It says nothing about task success, latency,
reliability or cross-browser support.

Honest caveat: Playwright and Puppeteer are broader general-purpose automation frameworks with huge ecosystems and cross-browser support. Grip is narrower on purpose — it does one thing (feed an LLM the smallest useful view of a page) and does not try to replace them for human-driven E2E testing.

### Grip vs browser-use

**On this comparison grip does not win.** browser-use is the closest competitor
grip has — Python, CDP-native since its 0.6.0 (it dropped Playwright as its
driver), MIT — so it is the one worth measuring, and the result goes the other
way. On the like-for-like payload, browser-use's DOM serialisation against
grip's snapshot over the same 8 pages, same encoder, same Chrome binary, no LLM
in either loop, **browser-use is 0.90x the size of grip's snapshot by
median-of-ratios and 0.81x by ratio-of-medians** — smaller on both statistics,
smaller on 4 of the 8 pages, and nearly 3x smaller on Wikipedia.

It is not a column in the table above because the two payloads are not the same
measurement, and the raw ratio misleads in both directions:

- **They do not describe the same amount of page.** browser-use serialises the
  viewport plus a 1000px margin; grip serialises the whole document. Its 6,778
  tokens on Wikipedia leave **26.9 viewport-heights unserialised**, and it pays
  again on every scroll turn. A smaller number can mean less page rather than
  denser encoding. Which is cheaper end to end depends on the task, and this
  benchmark does not measure that.
- **On the 3 pages where coverage is comparable the result is mixed** — 1.63x,
  1.07x and 0.56x browser-use ÷ grip, on Hacker News, arXiv and example.com.
  n=3. Nothing should be generalised from three pages; it is reported because it
  is the fairest cut this data allows, not because it rescues anything.
- **GitHub runs the other way.** browser-use is **4.15x larger** than grip there
  while still leaving 5.5 pages below unserialised — on a control-dense
  application shell its per-element encoding costs more, viewport limit and all.
- **Screenshots are excluded**, which favours browser-use: it runs with vision on
  by default and ships a base64 PNG alongside this text, while grip's figure is
  all grip sends.

They are also not substitutes. browser-use is a **full agent framework** — LLM
loop, action registry, memory, planning, filesystem, cloud execution, MCP
integration. grip is a **snapshot primitive**: it produces a compact view of a
page and does not run an agent. If you want an agent that browses, browser-use
does something grip does not do at all, and choosing between them on payload
size alone would be choosing on the wrong axis.

Per-page tables, both statistics, the 40,000-character cap, variance across
three runs and what this does not measure:
[`benchmarks/RESULTS_BROWSERUSE.md`](benchmarks/RESULTS_BROWSERUSE.md).

### When to use Grip

- You're building an autonomous or semi-autonomous agent that browses the web and you're paying per token.
- Your agent loop is blowing its context window on raw HTML or screenshots.
- You want typed, recoverable errors (`CAPTCHA_REQUIRED`, `RATE_LIMITED`, `ELEMENT_STALE`) instead of parsing exception strings.
- You need shadow DOM / web-component pages handled without special-casing.

### When not to use Grip

- You need cross-browser (Firefox/WebKit) human E2E test coverage — use Playwright.
- Your task is a fixed, deterministic scrape with known selectors and no LLM in the loop — a plain scraper is simpler.

### FAQ

**Is Grip a Playwright wrapper?** No. Grip talks to Chrome over the DevTools Protocol directly. There is no Playwright or Puppeteer dependency underneath.

**How does it cut tokens?** It sends the model only interactive elements (inputs, buttons, links) and visible text, indexed for fuzzy matching — not the full HTML tree, not a screenshot. On 2026-08-10 a trivial page like example.com came out at 50 tokens against 167 raw; the Wikipedia article on Python, the heaviest page in the corpus, came out at 19,946 against 459,193 raw.

**Which LLMs does it work with?** Anthropic, OpenAI, and Gemini adapters ship in the box, plus any OpenAI-compatible endpoint (Ollama, vLLM, LM Studio, OpenRouter, Together, Groq, ...) via `base_url`; any other model works via the `LLMAdapter` protocol.

**Does it handle CAPTCHAs / bot blocks?** It detects and classifies them (`page.detect_challenge()`), and returns a typed error with a suggested recovery action (escalate, backoff, rotate). `page.solve_challenge()` attempts checkbox, Turnstile and slider stages in-process and only reports success it can verify; image-grid and text challenges come back to your model with a screenshot. No third-party solving service is used, and success rates are unmeasured — see [Challenges and automation tells](#challenges-and-automation-tells).

**What do I need installed?** Python 3.11+ and Chrome or Chromium. Grip finds Chrome automatically, and falls back to the Chrome for Testing build that Playwright or Puppeteer already downloaded if no system Chrome is present. Set `CHROME_EXECUTABLE` to override.

---

## The problem

Most browser tools give AI agents raw HTML or screenshots. Raw HTML on a real page runs tens of thousands of tokens — a measured median of 58,912 across 8 popular sites on 2026-08-10, ranging from 167 on example.com to 459,193 for a single Wikipedia article. A PNG screenshot estimates at ~3,000 tokens, a JPEG at ~800 (grip's own `Screenshot.tokens_estimated`, a size estimate rather than a corpus measurement). The 58,280 median in the tables above is a separate arm — Puppeteer's `page.content()` on the same 8 pages — not a second reading of this one. Both burn through context windows fast and slow your agent down.

## What grip does instead

grip gives your agent a semantic summary of what's on the page — just the interactive elements and visible text, structured for LLM consumption:

```
PAGE: Amazon.com
URL: https://www.amazon.com/

INTERACTIVE:
  [inp:0] "search here" (placeholder)
  [btn:1] "Go"
  [btn:2] "Sign in"
  [lnk:3] "Returns & Orders"

CONTENT:
  Delivering to New York — Shop deals in...
```

**1,998 tokens per snapshot, median** across those 8 pages on 2026-08-10, but the range is 50 to 19,946 and the median is not what you should budget for. example.com, the smallest page on the web, is 50 tokens. The Wikipedia article on Python is 19,946 — against 459,193 raw.

---

## Quick start

```python
import asyncio
from grip import Browser

async def main():
    async with Browser(headless=True) as browser:
        page = await browser.open("https://news.ycombinator.com")
        snapshot = await page.snapshot()

        print(snapshot.text_content)      # readable page text
        print(snapshot.elements)          # interactive elements only
        print(snapshot.tokens_estimated)  # 3,540 for this page on 2026-08-10; 1,998 median across 8 real pages

asyncio.run(main())
```

## Full agent loop

```python
async with Browser(headless=True) as browser:
    page = await browser.open("https://amazon.com")
    await page.snapshot()               # build element index

    await page.type("search", "blue sneakers")
    await page.click("Go")              # fuzzy match — no selectors needed

    await page.snapshot()               # re-index after navigation
    doc = await page.read()             # prose, citable blocks, no nav chrome

    shot = await page.screenshot()      # JPEG, ~800 tokens for vision models
    shot.save("result.jpg")
```

## Concurrent pages

Every `open()` gets its own tab and its own CDP connection, so pages are
independent and can be driven in parallel:

```python
async with Browser(headless=True) as browser:
    urls = ["https://example.com", "https://example.org", "https://example.net"]
    pages = await asyncio.gather(*(browser.open(u) for u in urls))
    snapshots = await asyncio.gather(*(p.snapshot() for p in pages))

    for snap in snapshots:
        print(snap.url, snap.tokens_estimated)

    for page in pages:
        await page.close()          # closes the tab; browser.close() also closes any left open
```

`page.goto(url)` navigates an existing tab in place. There is no built-in
concurrency limit — wrap in an `asyncio.Semaphore` if you need one, since the
safe ceiling depends on your machine rather than on grip.

## Read mode

`snapshot()` answers "what can I click here". `read()` answers "what does this page
say" — main content isolated, navigation and footer chrome dropped, and every block
carrying the heading trail above it so a claim can be cited back to a location.

```python
async with Browser(headless=True) as browser:
    page = await browser.open("https://docs.python.org/3/library/asyncio-task.html")
    doc = await page.read()

    print(doc.outline())          # heading map of the page
    for block in doc.blocks:
        print(block.citation, block.text[:60])
        # [12] Coroutines and tasks › Coroutines   Source code: Lib/asyncio/...
```

`read(max_chars=N)` truncates by dropping whole blocks, never mid-sentence. The
default is no limit — deciding which parts of a page matter is ranking, and that
belongs to the caller.

## Challenges and automation tells

grip **detects** checkbox, Turnstile, slider, image-grid, text and invisible
challenges from the page's DOM and frame URLs, and classifies them without a
network call (`page.detect_challenge()`). Detection is tested against real widget
markup.

`page.solve_challenge()` implements in-process solve flows for the checkbox,
Turnstile and slider stages, using human-shaped pointer motion and no
third-party solving API. Each flow reports `"solved"` **only** after it verifies
the outcome — a response token is present, or the widget has left the page. If
neither is true when the timeout expires it returns `"timeout"`, never `"solved"`.
Image-grid and text challenges return `"needs_vision"` with a screenshot for your
own model to answer; grip does not ship a classifier. **Solve success rates are
unmeasured** as of 2026-08-10: they depend on IP reputation and provider-side
scoring, so any number quoted here without a stated egress would be meaningless.

```python
result = await page.solve_challenge(timeout=30.0)
match result.status:
    case "solved":       ...  # verified: token present or widget gone
    case "needs_vision": ...  # result.screenshot -> your model -> page.click_at(x, y)
    case "unsupported":  ...  # named in result.stage
    case "timeout":      ...  # NOT solved; the challenge is still there
    case "none":         ...
```

Human-shaped input is available on its own: `page.click_at(x, y, human=True)` and
`page.drag(start, end)` travel a curved, eased Bézier path with a randomized press
dwell. Straight-line constant-velocity motion is the clearest synthetic-input
tell. `page.click(desc, human=True)` uses that path instead of the JS click: it
re-resolves the element first, so it still raises `ELEMENT_STALE` on a stale
handle and clicks the element's live position rather than the one the snapshot
recorded. The default stays the JS path — it is faster and works headless —
and `human=True` is for challenge flows.

Chrome under CDP sets `navigator.webdriver` and puts `HeadlessChrome` in the user
agent. `Browser(stealth=True)` removes both. It is off by default because grip is a
general-purpose SDK and silently masking automation would surprise anyone using it
for ordinary testing. Measured once, on 2026-08-10, with
`evaluation/stealth_measurement.py`:

```
probe                                     stealth=False  stealth=True
https://bot.sannysoft.com/                10 tells        4 tells
https://abrahamjuliot.github.io/creepjs/   3 tells        0 tells

.venv/bin/python -m evaluation.stealth_measurement
```

Read that narrowly. These probes count the signals they choose to report, so
fewer tells is not "undetectable" — a service that scores rather than lists may
weigh signals these pages never surface. It was **not** tested against any live
anti-bot system: no reCAPTCHA, no Cloudflare challenge, no commercial bot
manager. It is one run on one machine, one Chrome build and one IP, so
run-to-run variance is unknown. It says nothing about TLS/JA3. And it does not
predict that a site will let you through — IP reputation usually decides that,
and neither flag touches it. (A competitor measured the *page-world shim*
approach against live reCAPTCHA and found it made detection easier; that is a
different mechanism — init scripts patching navigator from inside the page —
than the two launch flags measured here, so both results can hold.)

grip does **not** hide that it is automation at the network layer. TLS/JA3
fingerprints, and full headless fingerprint parity, live below the Chrome
DevTools Protocol and cannot be reached from a Python client driving stock
Chromium. If a site blocks you on IP reputation or TLS fingerprint, no flag in
this library will change that — that is an egress problem, and the answer is a
residential or mobile proxy, which grip supports via `proxy=`.

## With an LLM (autonomous mode)

```python
from grip import Browser
from grip.adapters.anthropic import AnthropicAdapter

llm = AnthropicAdapter(api_key="sk-ant-...")

async with Browser(llm=llm, headless=True) as browser:
    result = await browser.run(
        goal="Find the cheapest blue sneakers under $80",
        url="https://amazon.com"
    )
    print(result.data)
    print(f"Used {result.tokens} tokens")
```

grip handles the snapshot → decide → act loop automatically. You just provide the goal.

### Snapshot delta

Inside the run loop, grip sends the model a full snapshot on the first turn and a
delta after that — only the elements and content that changed.

Measured end to end, an agent driving grip spends **~18x fewer prompt tokens over
a 6-turn run than the same agent dumping `outerHTML`** (16.9x–18.4x across repeat
runs; 17.8x on the reported run, ranging 4.6x–41.8x across the four scenarios).
That figure is the median of the per-scenario ratios over four real sites, six
real turns each, counted with tiktoken `cl100k_base`.

**Most of that win is compression, not the delta,** and it is worth being clear
about which mechanism does what:

| | median | per-scenario range |
|---|---|---|
| compression — grip snapshot vs raw HTML, per turn | **11.3x** | 2.9x – 22.0x |
| delta — vs sending a full snapshot every turn, per turn | **1.0x** | 1.0x – 8.8x |
| pruning — superseded page states dropped, cumulative | **1.4x** | 1.0x – 2.2x |
| **end to end** — raw HTML vs grip delta + pruning, cumulative | **17.8x** | 4.6x – 41.8x |

The 11.3x compression figure is the large term, and any serious
accessibility-tree tool gets some version of it.

The delta's per-turn median is only 1.0x because `build_delta` returns `None` on
a URL change: on a navigation turn grip sends a full snapshot by design, and a
realistic agent run is mostly navigation. Three of the four scenarios had 0–2
same-document turns out of 6. **Where it pays is when an agent works within one
page** — filling a form, driving an SPA. On the 8 turns across all scenarios
where a delta could fire, repeat observations cost a median **9.1x** less, range
**0.5x–175.0x**. The 0.5x is a real defect the benchmark surfaced: on a
click-driven navigation where the reported URL lagged the document, grip diffed
two unrelated pages and emitted a delta *larger* than the snapshot it replaced.
It is documented, not smoothed away.

Pruning is a separate mechanism from the delta and is what carries
navigation-heavy runs: superseded page states are not re-sent, so cumulative
prompt cost grows with the number of turns rather than with their square.

Full method, per-scenario tables, stability across 20 runs and the things this
does **not** measure (task success, latency, model quality) are in
[`benchmarks/RESULTS_AB.md`](benchmarks/RESULTS_AB.md). Reproduce with:

```
.venv/bin/python benchmarks/bench_agent_ab.py
```

---

## Why not Playwright or Puppeteer?

| | Playwright MCP | Puppeteer | grip |
|---|:---:|:---:|:---:|
| Tokens per snapshot | 11,597 median | 58,280 median (HTML)<br>27,489 median (a11y tree) | **1,998 median** |
| Shadow DOM traversal | Partial | No | Full |
| Prompt injection guard | No | No | Yes |
| Typed error recovery | No | No | Yes |
| Element staleness detection | No | No | Yes |
| Pure CDP (no binary bloat) | No | No | Yes |
| Screenshot token tracking | No | No | Yes |

Token figures: 8 real pages, tiktoken `cl100k_base`, 2026-08-10 —
[`benchmarks/RESULTS_COMPETITORS.md`](benchmarks/RESULTS_COMPETITORS.md). Payload size
is one axis: Playwright and Puppeteer are broader general-purpose automation frameworks
and this table says nothing about task success, latency or cross-browser support.

This table covers Playwright MCP and Puppeteer only. The token column does **not**
generalise to every tool: browser-use's serialisation is *smaller* than grip's at the
median on the same corpus — see [Grip vs browser-use](#grip-vs-browser-use) for the
figures and for why the two are not measuring the same thing.

---

## Structured errors

Every error comes back as a typed `BrowserError` — not a bare string — so your agent can make decisions:

```python
from grip import GripError
from grip.errors.types import ErrorType, RecoveryAction

try:
    await page.click("checkout")
except GripError as e:
    match e.error.type:
        case ErrorType.CAPTCHA_REQUIRED:
            # recovery: ESCALATE_TO_HUMAN or VISION_FALLBACK
            await escalate(e.error.message)
        case ErrorType.RATE_LIMITED:
            # recovery: EXPONENTIAL_BACKOFF + RETRY
            await asyncio.sleep(30)
            await page.click("checkout")
        case ErrorType.AUTH_REQUIRED:
            # recovery: ESCALATE_TO_HUMAN
            raise NeedsLogin(e.error.message)
        case ErrorType.ELEMENT_STALE:
            # recovery: RE_SNAPSHOT + RETRY
            await page.snapshot()
            await page.click("checkout")
```

### Full error taxonomy

| Type | When | Suggested recovery |
|---|---|---|
| `ELEMENT_NOT_FOUND` | fuzzy match failed | re-snapshot, retry with different description |
| `ELEMENT_STALE` | element moved after navigation | re-snapshot |
| `ANTI_BOT_BLOCK` | Cloudflare, DDoS-Guard, 403 | rotate identity |
| `CAPTCHA_REQUIRED` | CAPTCHA challenge page | escalate to human |
| `RATE_LIMITED` | 429 Too Many Requests | exponential backoff |
| `AUTH_REQUIRED` | login wall | escalate to human |
| `ZERO_RESULTS` | page loaded, no matching content | retry, broaden query |
| `NETWORK_TIMEOUT` | navigation timed out | exponential backoff |
| `NAVIGATION_FAILED` | blank page / bad URL | retry |

---

## Shadow DOM

grip traverses shadow DOM trees automatically. Web components, Chrome extensions, custom elements — all discovered in the same snapshot:

```python
snapshot = await page.snapshot()
shadow_elements = [el for el in snapshot.elements if el.in_shadow_dom]
```

---

## Trace

Every action is recorded with timing and token cost:

```python
async with Browser() as browser:
    page = await browser.open("https://example.com")
    await page.snapshot()
    await page.click("Learn more")
    await page.screenshot()

print(browser.trace.total_tokens)   # total tokens used
browser.trace.to_jsonl("audit.jsonl")  # machine-readable audit log
```

---

## LLM adapters

grip ships with OpenAI, Anthropic, and Gemini adapters out of the box:

```python
from grip.adapters.openai import OpenAIAdapter
from grip.adapters.anthropic import AnthropicAdapter
from grip.adapters.gemini import GeminiAdapter

llm = OpenAIAdapter(api_key="sk-...")            # gpt-4o, gpt-4-turbo, etc.
llm = AnthropicAdapter(api_key="sk-ant-...")     # claude-opus-4-7, etc.
llm = GeminiAdapter(api_key="...")               # gemini-2.0-flash, etc.
```

`OpenAIAdapter` also takes a `base_url`, which is all that's needed to talk to
any OpenAI-compatible endpoint — Ollama, vLLM, LM Studio, OpenRouter,
Together, Groq, and anything else speaking the OpenAI wire format:

```python
llm = OpenAIAdapter(model="llama3", base_url="http://localhost:11434/v1")
# api_key defaults to a placeholder when base_url is set, since most local
# servers don't check it; pass one explicitly for hosted OpenAI-compatible
# providers that do (OpenRouter, Together, Groq, ...).
```

Or bring your own by implementing the `LLMAdapter` protocol:

```python
from grip.adapters.base import LLMAdapter, LLMResponse

class MyAdapter:
    async def complete(self, messages, tools) -> LLMResponse:
        ...
```

---

## Requirements

- Python 3.11+
- Google Chrome (or Chromium) installed

grip finds Chrome automatically. Override with `CHROME_EXECUTABLE` env var.

---

## Install

```bash
pip install grip-browser

# with OpenAI support
pip install grip-browser[openai]

# with Anthropic support
pip install grip-browser[anthropic]

# with Gemini support
pip install grip-browser[gemini]

# as an MCP server
pip install grip-browser[mcp]
```

---

## MCP Server

`grip-mcp` runs grip as a stdio MCP server — eight tools (`open`, `goto`,
`snapshot`, `click`, `type`, `read`, `screenshot`, `run`), the same delta
compression as the SDK, and no session registry (one browser, one page, per
process). Copy-paste config for Claude Code, Claude Desktop, and Cursor, plus
the full tool reference: **[docs/mcp.md](docs/mcp.md)**.

---

## Measured numbers

Everything in this table was measured on this branch. Anything not in it is not
claimed: cold-start time, memory, requests per second and challenge solve rates
are all unmeasured, and quoting them would be a guess. Tokens against other
tools ARE measured — Playwright MCP and Puppeteer, in
[`benchmarks/RESULTS_COMPETITORS.md`](benchmarks/RESULTS_COMPETITORS.md), and
browser-use, which comes out *smaller* than grip at the median, in
[`benchmarks/RESULTS_BROWSERUSE.md`](benchmarks/RESULTS_BROWSERUSE.md). The
snapshot-size figures live in [Why Grip](#why-grip) with their own method note.

| | Measured | How |
|---|---|---|
| Prompt tokens over a 6-turn run, grip vs raw HTML | **17.8x fewer** (4.6x–41.8x per scenario; 16.9x–18.4x across repeat runs) | median of per-scenario ratios, 4 live sites × 6 real turns, tiktoken `cl100k_base`; [`benchmarks/RESULTS_AB.md`](benchmarks/RESULTS_AB.md) |
| — of which compression, per turn | 11.3x (2.9x–22.0x) | grip snapshot vs `outerHTML` of the same DOM state, same run |
| — of which delta, per turn | 1.0x (1.0x–8.8x) | vs sending a full snapshot every turn; `build_delta` returns `None` on navigation, so most turns send a full snapshot |
| — of which pruning, cumulative | 1.4x (1.0x–2.2x) | superseded page states dropped from the transcript; independent of the delta |
| Delta saving on same-document turns | 9.1x median (0.5x–175.0x) | the 8 turns of 24 where a delta fired; the 0.5x is the URL-lag defect documented in the results file |
| Cumulative prompt cost over a run | grows with turns, not turns² | superseded page states are not re-sent |
| Unit tests | 249 pass | `pytest tests/unit` |
| gripsearch tests | 33 pass | `pytest` in `gripsearch/` |
| Integration tests | 74 pass | real Chrome, live network |
| Unit coverage | 84.18% | unit tests only; CI fails below 80 |
| Lint | ruff 83 → 0 | both gates previously passed vacuously because neither was configured |
| Types | mypy `--strict` 35 → 0 | as above |
| example.com, live | open 0.80s, snapshot 0.01s, 1 element, 50 tokens | headless Chrome, single page |
| Local file fixture | open 0.61s, snapshot 0.01s | `file://` page, no network |
| Chrome profile directories stranded | 0 | across a 57-minute full-suite run |

Test and lint counts are for this branch and will move. Re-run them rather than
trusting the table if the number matters to you.

---

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for dev
setup, running tests, and lint/type-check commands. Please also read the
[Code of Conduct](CODE_OF_CONDUCT.md). Found a security issue? See
[SECURITY.md](SECURITY.md) instead of opening a public issue.

---

## License

MIT — see [LICENSE](LICENSE).
