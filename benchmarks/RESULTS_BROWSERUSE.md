# Observation payload size: grip vs browser-use

Date: 2026-08-10. Three runs, 71.6s / 63.6s / 71.6s wall. Encoder: **tiktoken
`cl100k_base`** for every column without exception.

```
python3 -m venv ~/scratch/browseruse/.venv
~/scratch/browseruse/.venv/bin/python -m pip install browser-use==0.13.7
.venv/bin/python benchmarks/bench_browseruse.py [--out results.json]
```

## Why this file exists

`RESULTS_COMPETITORS.md` measured Playwright MCP and Puppeteer and did not
measure browser-use. That was the wrong omission to make. browser-use is the
closest competitor grip has — Python, CDP-native (it dropped Playwright as its
driver in 0.6.0), MIT — and grip's claimed wedge, "Python-native, no Playwright
dependency," describes browser-use as accurately as it describes grip. A
comparison table that skips the nearest competitor is one a reader is entitled
to be suspicious of.

**Headline, stated before the caveats rather than after them: on the payload
browser-use actually serialises, grip does not win.** browser-use's DOM
serialisation is **0.90x** the size of grip's snapshot by median-of-ratios and
**0.81x** by ratio-of-medians — smaller on both statistics — and it is smaller
on 4 of the 8 pages. The reason is structural and is explained below; it is not
a measurement error, and it is not a reason to discount the number.

## What was measured, and how that was determined

browser-use has no single "snapshot" call, so the payload had to be located in
its source rather than assumed. Reading from the agent loop downwards:
`Agent._get_next_action` (`agent/service.py:1170`) → `MessageManager.create_state_messages` (`agent/message_manager/service.py:421`) →
`AgentMessagePrompt.get_user_message()`, whose `<browser_state>` section is
built by `AgentMessagePrompt._get_browser_state_description()`
(`browser_use/agent/prompts.py:224`), which calls
`SerializedDOMState.llm_representation()` (`browser_use/dom/views.py:939`).
That is the text browser-use puts in the model's context each turn.

Two columns are reported because two are defensible:

| column | what it is |
|---|---|
| `browseruse_dom` | `llm_representation(include_attributes=...)` — the interactive-element serialisation. The direct counterpart of grip's `Summarizer.format(snapshot)` and of Playwright MCP's snapshot text. |
| `browseruse_block` | `_get_browser_state_description()` — the literal `<browser_state>` block: the above plus browser-use's own framing (`<page_stats>`, tab list, `<page_info>`, `[Start of page]`/`[End of page]`, the `Interactive elements:` header). |

The block is what browser-use actually sends. The DOM serialisation is the
like-for-like comparison, because the framing has no grip analogue. Both are in
the table; the ratio section reports both.

`include_attributes` is `AgentSettings().include_attributes`, asserted at run
time to be identical to `DEFAULT_INCLUDE_ATTRIBUTES` (55 attributes). This
mattered: `MessageManager` does `include_attributes or []`, and passing `[]`
would have stripped every attribute and understated browser-use's payload by a
large margin.

**No LLM is in the loop.** `BrowserSession` produces the state without a model,
so no API key is required and nothing here measures model output.

**Screenshots are excluded** (`get_browser_state_summary(include_screenshot=False)`).
browser-use runs with vision on by default, so its real per-turn cost is this
text *plus* a base64 PNG. Text is what grip produces, so text is what is
compared. The omission is in browser-use's favour.

**The comparison is like-for-like on interaction refs.** browser-use's
serialisation carries `[363]` indices the model uses to target actions; grip's
carries `[btn:e3]`-style refs. Both are counted.

## Versions

| | |
|---|---|
| grip | 0.5.1 |
| browser-use | 0.13.7 (latest on PyPI at time of run) |
| tiktoken | 0.13.0 |
| python (both venvs) | 3.14.5 |
| Chrome | `~/Library/Caches/ms-playwright/chromium-1234/chrome-mac-arm64/Google Chrome for Testing` |

browser-use was installed into `~/scratch/browseruse/.venv`, **not** grip's venv:
it pulls a large dependency tree (`mcp`, `google-auth`, `pyobjc`, an LLM client
stack) that has no business in grip's environment. Both arms drive the *same*
Chrome binary — grip's `find_chrome()` result is passed to browser-use as
`executable_path` — so no part of the gap is a different renderer.

Pages: the same 8 URLs as `benchmarks/bench_competitors.py`, so these columns
line up with `RESULTS_COMPETITORS.md`. See that file for why those URLs are a
reconstruction rather than the exact set behind README's published figure.

## Per-page tokens

Run A (run B differed by at most 2 tokens on any browser-use cell; see
Variance):

| page | raw_html | grip | browseruse_dom | browseruse_block | bu chars | truncated | pages below |
|---|---:|---:|---:|---:|---:|:--:|---:|
| wikipedia | 459,198 | 19,946 | **6,778** | **6,891** | 19,394 | no | 26.9 |
| github | 171,021 | **2,510** | 10,407 | 10,516 | 28,972 | no | 5.5 |
| react.dev | 103,848 | 1,550 | **1,134** | **1,222** | 3,690 | no | 13.4 |
| bbc | 112,127 | 2,395 | **1,134** | **1,231** | 4,151 | no | 4.6 |
| hacker news | 13,662 | **3,533** | 5,775 | 5,884 | 12,942 | no | 0.3 |
| python docs | 8,818 | **1,077** | 1,527 | 1,640 | 4,889 | no | 1.8 |
| arxiv | 15,051 | **1,570** | 1,682 | 1,788 | 5,145 | no | 0.3 |
| example.com | 167 | 50 | **28** | 112 | 138 | no | 0.0 |

Bold = smaller payload on that page. Every arm produced a number on all 8 pages
(n=8/8). No cell is estimated, extrapolated, or read off documentation.

`bu chars` is the untruncated character length of `browseruse_dom`.
`truncated` is whether the 40,000-character cap fired (see below); it did not
fire on any page here. `pages below` is how many viewport-heights of the page
sit *below* the region browser-use serialised — the coverage column, and the
most important one in the table.

## Both statistics, named

The ratio is **browser-use ÷ grip**, so a value above 1.00 means grip's payload
is smaller and a value below 1.00 means browser-use's is.

| page | dom ÷ grip | block ÷ grip |
|---|---:|---:|
| wikipedia | 0.34 | 0.35 |
| github | 4.15 | 4.19 |
| react.dev | 0.73 | 0.79 |
| bbc | 0.47 | 0.51 |
| hacker news | 1.63 | 1.67 |
| python docs | 1.42 | 1.52 |
| arxiv | 1.07 | 1.14 |
| example.com | 0.56 | 2.24 |

| statistic | dom ÷ grip | block ÷ grip |
|---|---:|---:|
| **median of per-page ratios** | **0.90** | 1.33 |
| ratio of medians | 0.81 | **0.86** |
| range | 0.34 – 4.15 | 0.35 – 4.19 |

Bold marks the statistic that is *less* flattering to grip in each column;
that is the one to quote. The two disagree in direction on the block column —
median-of-ratios says grip's payload is 1.33x smaller, ratio-of-medians says it
is 0.86x, i.e. larger — which is exactly why both are printed. Quoting only the
1.33 would be picking the number that wins.

**Pages where browser-use's payload is smaller than grip's:** wikipedia,
react.dev, bbc, example.com on the DOM column (4 of 8); wikipedia, react.dev,
bbc on the block column (3 of 8). On wikipedia the gap is nearly 3x in
browser-use's favour.

**Pages where grip's payload is smaller:** github (4.15x), hacker news (1.63x),
python docs (1.42x), arxiv (1.07x); example.com on the block column (2.24x).

example.com is the one page where the two columns land on opposite sides of
1.00 (0.56 vs 2.24). Nothing changed about the page: on a payload of 28 tokens,
browser-use's ~84 tokens of fixed framing dominate. The framing is close to a
constant, so it matters enormously on a trivial page and not at all on a real
one.

## The coverage difference, which explains most of the above

**The two payloads do not describe the same amount of page.** browser-use's
serialiser keeps only nodes inside the viewport plus a 1000px margin —
`DomService.is_element_visible_according_to_all_parents`, `viewport_threshold`
default `1000` (`browser_use/dom/service.py:252`). What is below that region is
represented only by a one-line hint in the block —
`<page_info>0.0 pages above, 26.9 pages below — scroll down to reveal more
content</page_info>` — plus `|scroll element| (…)` annotations on individual
scrollable containers. grip serialises the whole document.

So the `pages below` column is not decoration. On wikipedia browser-use's 6,778
tokens describe a view with **26.9 viewport-heights of page still below it**;
grip's 19,946 tokens describe the entire article. (The `13.4 pages below` that
appears in the wikipedia sample text further down is a different number: it is
the scroll state of the nested main-menu `<div>`, not of the page. The page
figure is the one in `<page_info>`, verified against the captured block text:
26.9.) That is not grip losing a
compression contest, and it is not browser-use cheating: it is a different
product decision. browser-use pays again on each scroll turn; grip pays once.
Which is cheaper end-to-end depends on the task, and **this benchmark does not
measure that.**

Read the rows where coverage is comparable and the picture changes:

| page | pages below | dom ÷ grip |
|---|---:|---:|
| hacker news | 0.3 | 1.63 |
| arxiv | 0.3 | 1.07 |
| example.com | 0.0 | 0.56 |

Three pages, mixed result, n far too small to generalise from. It is reported
because it is the fairest cut available from this data, not because it rescues
anything.

The github row runs the other way: browser-use is 4.15x *larger* than grip while
still leaving 5.5 pages below unserialised. On a control-dense application shell
its per-element encoding costs more than grip's, viewport limit and all.

## The 40,000-character cap

`AgentMessagePrompt` truncates the element text at
`max_clickable_elements_length=40000` characters — the default in
`AgentMessagePrompt.__init__`, in `AgentSettings` (`agent/views.py:92`) and in
`Agent.__init__` (`agent/service.py:209`). It applies to `browseruse_block` and
not to `browseruse_dom`.

**It did not fire on any of these 8 pages** — the largest serialisation was
github at 28,972 characters. It is documented here because it would silently cap
the block column on a heavier page, and a capped payload reported as a small one
would be a false win for browser-use. The harness records the untruncated
character count and a `truncated` flag on every row so that case is visible
rather than inferred.

## Variance

Three full runs (the third after a harness edit, kept because it is another
sample). Between runs A and B, browser-use cells moved by at most **2 tokens**
on any page (wikipedia 6,778 → 6,776; github 10,407 → 10,406) — under 0.03%.
Run C moved one cell meaningfully: react.dev 1,134 → 1,107 (−2.4%), a live page
serving slightly different content, and grip's react.dev figure was unchanged at
1,550. Every other browser-use cell in run C was within 2 tokens of run A.
grip's cells moved by at most 1 token across all three runs (bbc 2,395/2,396).
`raw_html` moved most, as expected from live pages: react.dev +441, bbc +149,
github +58 between A and B, and arxiv 15,051 → 14,014 (−7%) in run C.

Across the three runs the summary statistics were stable: median-of-ratios
0.90 / 0.90 / 0.89 and ratio-of-medians 0.81 / 0.81 / 0.81 on the DOM column.
The table above is run A; no run changes which pages browser-use wins. A fourth
run, made only to check the reporting code after an edit, reproduced 0.90 /
0.81 and the same win list.

The stability is worth noting for a second reason: it is evidence the capture is
real. Both arms produce page-shaped numbers spanning 28 to 20,000 tokens that
reproduce to within a couple of tokens, rather than a constant.

## Did the capture actually work

`RESULTS_COMPETITORS.md` records a run where Playwright MCP reported a constant
32 tokens on all 8 pages because an error string was being tokenised as a
snapshot. That failure mode is guarded here in three ways:

1. The harness prints the first 200 characters of every browser-use
   serialisation, and those were read before any number was trusted. They are
   page-specific, structured, and obviously real:
   ```
   wikipedia    Jump to content\n[355]<nav aria-label=Site />\n	[357]<div id=vector-main-menu-dropdown ...
   hacker news  [30]<a />\n[4]<a />\n	Hacker News\n[36]<a />\n	new\n[39]<a />\n	past\n[42]<a />\n	comments...
   example.com  Example Domain\nThis domain is for use in documentation examples ...\n[18]<a />\n	Learn more
   ```
2. browser-use's own empty-state strings (`Empty DOM tree ...`, `empty page`)
   are detected and force the cell to `unmeasured` with the reason, never a
   number.
3. `state_error` from `BrowserStateSummary` is surfaced per page.

The one genuinely small number, example.com at 28 tokens, is small because
example.com is 167 tokens of raw HTML. The sample text above is the whole
payload.

## What this does NOT measure

Everything that matters other than payload size:

- **Task success.** Neither tool is asked to do anything here. A smaller payload
  that omits the element the agent needed is worse than a larger one that
  includes it, and this benchmark cannot tell you which happened.
- **Latency, reliability, cost per completed task.** Not measured. browser-use's
  viewport-scoped payload implies more turns on long pages; more turns cost
  tokens too, and those are not counted here.
- **Scope, and this is the big one.** browser-use is a **full agent framework**:
  an LLM loop, a tool/action registry, memory, planning, a file system, cloud
  execution, MCP integration. grip is a **snapshot primitive** — it produces a
  compact view of a page and does not run an agent. They are not substitutes.
  A reader who picks a tool from this table alone will pick badly: if you want an
  agent that browses, browser-use does something grip does not do at all.
- **Screenshots**, excluded above, which are part of browser-use's default turn.
- **Anything about the other pages on the internet.** Eight pages, one day, one
  Chrome, two runs.

The honest summary is narrow: on these 8 pages, measuring only the text payload
per observation, grip and browser-use are in the same range, browser-use is
smaller at the median on the like-for-like column, and the largest single gaps
run in both directions and are mostly explained by browser-use serialising less
of the page.

## Reproducing

```
python3 -m venv ~/scratch/browseruse/.venv
~/scratch/browseruse/.venv/bin/python -m pip install browser-use==0.13.7
.venv/bin/python benchmarks/bench_browseruse.py --out results.json
```

`bench_browseruse.py` writes its own capture script into
`~/scratch/browseruse/` and runs it with that venv's interpreter, so the two
dependency trees never meet. It passes grip's resolved Chrome path to
browser-use, and sets `ANONYMIZED_TELEMETRY=false` and
`BROWSER_USE_CLOUD_SYNC=false` so the run does not phone home.

Network access is required: all 8 pages are live public sites fetched at run
time. There are no fixtures and no cached state. Each arm drives its own browser
instance, so the two see each page at slightly different moments; expect
run-to-run movement on the news-shaped pages in particular.
