# What grip saves an agent: a three-way A/B measurement

Date: 2026-08-10. grip 0.5.0, branch `hardening-and-delta`.
Encoder: **tiktoken `cl100k_base`** — the same encoder `Summarizer.count_tokens` uses.

```
.venv/bin/python benchmarks/bench_agent_ab.py
```

One command, no fixtures, no cached state, no arguments. It launches headless Chrome,
drives four scenarios against live public sites through grip's own `page.goto` /
`page.click` / `page.type`, and prints every table below. Takes 60–80 seconds.

## Method

Each scenario is 6 agent turns. Every turn is a real navigation, click or keystroke —
nothing is a synthetic DOM mutation. After each action the page is snapshotted once, and
the raw HTML is captured **adjacently, with no action in between**, so all three modes
describe the same DOM state.

Three observation channels are scored from that one capture:

| mode | payload sent to the model each turn |
|---|---|
| **A — no grip** | `document.documentElement.outerHTML` (a plain CDP/Playwright loop, no compression layer) |
| **B — grip, full snapshot** | `Summarizer.format(snapshot)` every turn — what an accessibility-tree approach costs |
| **C — grip, delta** | full snapshot on turn 1, `format_delta` afterwards |

Mode C is reported twice: with and without the runner's supersede-pruning. Those are two
separate mechanisms and only one of them is the delta, so they are not merged.

Three numbers per mode:

- **per-turn payload** — tokens in that turn's observation, on its own.
- **cumulative prompt tokens** — the sum over turns of what each turn's *entire message
  list* would cost. An agent re-sends its history every turn, so this is what the run
  bills.
- **peak single prompt** — the largest single request in the run. Cumulative and peak
  answer different questions: cumulative is what it costs, peak is whether it runs at all.
  A context window is a limit on peak, never on cumulative.

The message shape is identical in all four columns: the runner's real system prompt, the
goal in the opening user message, then an assistant tool-call frame plus a fenced tool
result per turn, plus OpenAI's documented 4-token-per-message framing. Only the payload
string differs. Mode A pays for a system prompt too — an agent driving raw CDP still needs
one.

Mode C mirrors `Runner._page_payload` exactly, including the `_last_sent_version` gate: a
delta is only counted as sent when its baseline is a snapshot the model actually received.
Pruning mirrors `Runner._prune_superseded`, matching on the fenced `PAGE:` prefix.

All ratios below are **medians of the per-scenario ratios**, not ratios of medians. The
latter divides one scenario's number by a different scenario's number whenever the
middle-ranked scenario differs between the two columns.

## Per-scenario results

Reported run: the most recent run that completed all four scenarios, 2026-08-10. It is
also a run that *exhibits* the delta defect described below rather than hiding it.

Per-turn observation payload, tokens:

| scenario | turns | delta turns | A raw HTML (med / max) | B grip full (med / max) | C grip delta (med / max) |
|---|---|---|---|---|---|
| hackernews | 6 | 1 | 13,961 / 15,124 | 3,325 / 3,573 | 3,217 / 3,573 |
| wikipedia | 6 | 1 | 137,907 / 159,186 | 6,864 / 16,101 | 6,864 / 16,101 |
| pythondocs | 6 | 1 | 54,013 / 73,131 | 2,925 / 5,297 | 2,924 / 5,297 |
| form-fill | 6 | 5 | 532 / 532 | 185 / 187 | 21 / 179 |

Cumulative prompt tokens across the whole 6-turn run:

| scenario | A raw HTML | B grip full | C grip delta | C delta + pruning | A / C-pruned |
|---|---|---|---|---|---|
| hackernews | 293,611 | 71,750 | 61,829 | 39,253 | 7.5x |
| wikipedia | 2,648,910 | 171,027 | **184,938** | 95,573 | 27.7x |
| pythondocs | 1,038,423 | 61,484 | 49,872 | 35,567 | 29.2x |
| form-fill | 12,504 | 5,190 | 2,711 | 2,711 | 4.6x |

Peak single prompt:

| scenario | A raw HTML | B grip full | C grip delta | C delta + pruning |
|---|---|---|---|---|
| hackernews | 84,454 | 20,291 | 16,984 | 7,406 |
| wikipedia | 719,034 | 45,214 | 49,851 | 21,344 |
| pythondocs | 311,129 | 19,825 | 16,922 | 8,586 |
| form-fill | 3,519 | 1,437 | 602 | 602 |

The bolded wikipedia cell is not a typo: in this run mode C cost **more** than mode B on
that scenario. See "A real defect this benchmark surfaced".

## Headline — median of the per-scenario ratios

| comparison | median | per-scenario range |
|---|---|---|
| **compression** (B vs A), per-turn | **11.3x** | 2.9x – 20.1x |
| **delta** (C vs B), per-turn | **1.0x** | 1.0x – 8.8x |
| **pruning** (C-pruned vs C), cumulative | **1.5x** | 1.0x – 1.9x |
| **grip end to end** (A vs C-pruned), cumulative | **17.6x** | 4.6x – 29.2x |

The single number for a landing page is **~18x fewer prompt tokens across a 6-turn run**
(16.9x–18.4x across repeat runs, see Stability), and it is dominated by compression, not
by the delta. That split is the honest reading:

- **B vs A (11.3x) is the compression win.** It is the large one, and every serious
  accessibility-tree tool gets some version of it.
- **C vs B is 1.0x per-turn as a median across scenarios.** `build_delta` returns `None`
  on a URL change, so on a navigation turn grip sends a full snapshot by design and mode C
  is byte-identical to mode B. Three of the four scenarios had 0–2 same-document turns out
  of 6. On the one scenario that stays on a single document (form-fill) the delta is 8.8x.
- **Pruning (1.5x cumulative) is where mode C's transcript advantage actually comes from
  in navigation-heavy runs**, and it is independent of the delta. It removes the O(n²)
  term by replacing superseded page states in the history. It contributes 1.0x on
  form-fill, where there is only ever one full snapshot to supersede, and 1.9x on
  wikipedia, where every turn is a fresh large document.

### What the delta is worth on the turns where it can fire

8 turns across the four scenarios were treated as same-document and emitted a delta:

| delta payload | full snapshot of the same state | saving |
|---|---|---|
| 19 | 3,325 | 175.0x |
| **4,655** | **18** | **0.004x — the delta cost 259x more** |
| 23 | 2,925 | 127.2x |
| 22 | 182 | 8.3x |
| 21 | 184 | 8.8x |
| 21 | 186 | 8.9x |
| 10 | 186 | 18.6x |
| 20 | 187 | 9.4x |

Median per-turn saving **9.1x**. The three-figure ratios are the large content pages; the
single-digit ones are the 13-element httpbin form, where the full snapshot is only 186
tokens to begin with.

### A real defect this benchmark surfaced

The pathological row is not noise, and it is the most useful thing here.

`build_delta` decides "same document" by comparing the URL that `Target.getTargetInfo`
reports. That URL can lag the document. When it does, grip diffs two unrelated DOM states,
concludes that everything was removed and everything else added, and emits a wholesale
replacement that is larger than simply re-sending the page.

Two variants were observed:

1. **Hacker News, click-driven navigation.** `click('comments')` navigated to
   `/newcomments`, but the snapshot still reported `/news?p=2`. Delta 5,701 tokens where
   the full snapshot was 2,963.

   ```
       5. goto('.../news?p=2')  -> https://news.ycombinator.com/news?p=2   els=230  full
       6. click('comments')     -> https://news.ycombinator.com/news?p=2   els=201  delta
   ```

2. **Wikipedia, transient empty page.** `click('Search')` left the page momentarily
   snapshotting to **0 elements** on the same URL. The delta described the removal of all
   773 elements plus the content — 4,655 tokens against an 18-token full snapshot, and it
   pushed mode C's cumulative above mode B's for that whole scenario.

This fired in 6 of the 22 runs (5 on hackernews, 1 on wikipedia). It is timing-dependent,
so it comes and goes. The benchmark now flags it explicitly
(`<-- delta COST MORE than the full snapshot`) rather than letting it vanish into a median.

Two things follow, and neither is fixed here:

- **grip does not guard against a delta being larger than the snapshot it replaces.** A
  `min(delta, full)` choice at the send site would bound the worst case at "no worse than
  mode B".
- **The URL guard trusts a URL that can lag the document.** Note that this benchmark
  sleeps 1.5s after every action before snapshotting; `Runner._dispatch` snapshots
  *immediately* after `click()` with no settle at all, so **the shipped agent loop is more
  exposed to this than these numbers show**, not less.

## Context window

Verdicts below are keyed on **peak single prompt**, not cumulative — no single request
ever carries the cumulative figure.

| scenario | peak prompt, mode A | peak prompt, C-pruned | verdict |
|---|---|---|---|
| hackernews | 84,454 | 7,406 | both fit in 200k |
| wikipedia | **719,034** | 21,344 | mode A is **3.6x a 200k window** |
| pythondocs | **311,129** | 8,586 | mode A **exceeds 200k**, crossing at turn 4 |
| form-fill | 3,519 | 602 | both fit |

Across all 22 runs the largest single raw-HTML *observation* seen was **373,479 tokens** —
the English Wikipedia article on HTML. Stated plainly: a naive agent that dumps
`outerHTML` cannot put that page into a 200k-token context even once, before any history
at all. The largest grip observation seen anywhere across those runs was 27,489 tokens.

## Stability

22 runs on 2026-08-10. The headline metric (median of per-scenario ratios) was added
partway through; across the runs that completed all four scenarios and printed it:

- compression B vs A: **11.3x in every such run**
- delta C vs B: 1.0x–1.1x
- pruning: 1.4x–1.5x
- end to end A vs C-pruned: **16.9x–18.4x**

The end-to-end spread is largely whether the delta defect above fires: runs where it does
land near 17.0x, runs where it does not land near 18.3x.

Per-scenario cumulative token variance across the repeat runs:

| scenario | A raw HTML | B grip full | C-pruned | A / C-pruned |
|---|---|---|---|---|
| hackernews | 287,683–300,637 (±4%) | 70,675–71,824 (±1.6%) | 38,857–45,230 (±16%) | 5.1x–7.7x |
| wikipedia | 2,639,801–4,206,537 (±59%) | 135,987–175,326 (±29%) | 63,213–95,573 (±51%) | 27.7x–60.1x |
| pythondocs | 1,031,598–1,044,771 (±1.3%) | 61,175–62,831 (±2.7%) | 35,464–36,016 (±1.6%) | 28.9x–29.2x |
| form-fill | 12,504 (0%) | 5,190 (0%) | 2,711 (0%) | 4.6x |

wikipedia is the unstable scenario. `click('Data mining')` and `click('HTML')` land on
articles whose rendered DOM varies substantially run to run (element counts moved between
339 and 1,273), and `click('Search')` sometimes opens an in-page widget, sometimes
navigates to `Special:Search`, and once snapshotted to zero elements. Both the raw-HTML
and the grip columns move together, so its ratio is steadier than either column alone, but
it still ranged 27.7x–60.1x. The headline median is stable because it is a median over
four scenarios, two of which vary by under 4%.

## What was dropped, and what is flaky

The benchmark drops a whole scenario when any step fails, and prints it as dropped with
the page title, URL, element count and page-error verdict at the moment of failure. It
never substitutes or estimates a number. Observed across 22 runs:

- **hackernews dropped in 4 of 22 runs**, with `ELEMENT_NOT_FOUND` on `comments`, `past`
  or `input`. In each case the snapshot at that moment had **0 elements**. HN
  intermittently serves degraded or throttled responses to repeated automated hits.
- **form-fill dropped in 3 of 22 runs**, late in the session: twice with the page titled
  `503 Service Temporarily Unavailable` and 0 elements, once with a CDP
  `Runtime.evaluate` timeout. httpbin.org rate-limits under repeated runs. A reader
  running the benchmark once or twice is unlikely to hit this.
- Worth noting separately: in every 0-element case grip reported `page_error=none`. A page
  that returns a 503 and snapshots to nothing is not being classified as a failure.
- The hackernews scenario clicks only masthead links (`comments`, `past`). Clicking story
  links is the more natural agent path, but their text changes hourly and a scenario that
  drops itself every few runs measures HN's front page rather than grip.
- The form-fill inputs are addressed by ref (`e1`, `e2`, …) rather than by label, because
  httpbin's form carries its labels as sibling text and every input reaches the snapshot
  with an empty label. Refs are what the snapshot shows the model, so this is a real agent
  path — but it is also a real limitation worth naming: grip's semantic matcher cannot
  currently address an unlabelled input.
- The `form-fill` scenario is a deliberately tiny page (532 tokens of raw HTML). It is
  included because it is the same-document case the other three lack, and it drags the
  compression median *down*, not up: median compression over just the three content sites
  is 18.5x rather than 11.3x. Both numbers are here; 11.3x is the headline.
- When scenarios drop, the headline shifts substantially, because a median over two or
  three scenarios is a different statistic. Runs with drops printed 18.5x–24.0x
  compression and 29.2x–44.2x end to end. **Only compare runs that completed all four
  scenarios.** The script prints the completed/dropped count at the top for exactly this
  reason.

## What this does not measure

This measures **observation tokens only**. It says nothing about:

- **task success** — whether an agent actually completes the goal in either mode. A
  compressed observation that omits the thing the model needed is cheaper and worse, and
  this benchmark cannot tell the difference.
- **latency** — grip's snapshot costs CDP round trips and JS execution that a raw
  `outerHTML` dump does not. See `benchmarks/bench_grip.py` for those numbers.
- **model quality** — no model was in the loop. The transcripts are constructed from real
  page states, but no LLM read them, so nothing here says a model reasons as well over a
  delta as over a full snapshot.
- **output tokens or cost in currency** — prompt tokens only, no pricing applied.

Fragment navigation is worth naming too: clicking an in-page anchor changes the URL that
`Target.getTargetInfo` reports, so `build_delta` returns `None` and grip sends a full
snapshot even though the document did not change. That is visible in the pythondocs turn
log (`click('Coroutines')` → `full`) and is a real ceiling on how often the delta fires.

## Reproducing

```
.venv/bin/python benchmarks/bench_agent_ab.py
```

The script prints, below the tables, a turn-by-turn log of every scenario: the action, the
resulting URL, the element count, and whether that turn sent a delta or a full snapshot.
Check that log against the tables — if the run did something other than what is claimed
here, the log will say so. From the reported run:

```
  hackernews: deltas emitted on 1/6 turns, 3 page states pruned
    1. goto('https://news.ycombinator.com')  -> news.ycombinator.com/   els=229  full
    2. click('comments')                     -> /newcomments            els=209  full
    3. click('past')                         -> /front                  els=203  full
    4. type('input', 'rust')                 -> /front                  els=203  delta
    5. goto('.../news?p=2')                  -> /news?p=2               els=230  full
    6. click('comments')                     -> /newcomments            els=209  full

  wikipedia: deltas emitted on 1/6 turns, 3 page states pruned
    ...
    4. click('Search')                       -> /wiki/Web_crawler       els=0    delta   <- the defect
```
