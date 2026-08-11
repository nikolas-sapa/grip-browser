# Task success: grip vs browser-use, agent loop in the loop

Date: 2026-08-11. First benchmark in this repo that measures whether a task
actually got done, not payload bytes. `RESULTS_AB.md` and
`RESULTS_BROWSERUSE.md` measured observation size with no LLM in the loop;
both said explicitly that they could not tell a good observation from a bad
one. This one puts a real model in the loop and scores completion.

**Coverage: 60 of 60 rows, complete.** The run finished; wizard-09 (browser-use
fail) and wizard-10 (browser-use pass) are the last two rows in.

**Lead with the loss: browser-use has the higher success rate, and the final
gap is wider than the interim table showed.**

| arm | overall | driven by |
|---|---|---|
| grip | 20/30 = 66.7% | forms 10/10, wizards 10/10, **SPA 0/10** |
| browser-use | 24/30 = 80.0% | forms 10/10, SPA 7/10, wizards 7/10 |

## Per-category table

| category | grip | browser-use |
|---|---|---|
| form | 10/10 | 10/10 |
| SPA | **0/10** | 7/10 |
| wizard | 10/10 | 7/10 |

Aggregate numbers hide this. Both arms are perfect on forms. grip loses SPA
completely and wins wizards outright. browser-use wins overall only because
SPA is a third of the corpus and grip scores zero on it.

## SPA: grip's 0/10, explained

This is a structural gap, not model failure or flakiness — the uniform 0/10
across 10 different fixtures is itself the evidence. `gripIsCandidate()`
(`grip/cdp/shadow.py:111-113`) admits an element to the snapshot only if its
tag is in a fixed interactive-tag list or its ARIA role is in a fixed
interactive-role list:

```js
function gripIsCandidate(el, tag, role) {
  return INTERACTIVE_TAGS.has(tag) || INTERACTIVE_ROLES.has(role);
}
```

The SPA fixtures' catalog items are non-semantic `<div>`s with JS click
listeners — no `<button>`, no `role="button"`. They never enter the
snapshot, so the model has no ref to click, and `click()` correctly returns
`ELEMENT_NOT_FOUND` on every attempt. `page.click_at(x, y)` exists in
`grip/page.py:1230` and would work around this, but it is not in the
registered tool set (`grip/runner.py:19`, `_TOOLS` = snapshot, click, type,
select, read, done — 6 tools, no `click_at`).

The harness does not log a per-turn error string, so the exact tool-error
text on each failed attempt isn't captured in the results file. What is
verifiable from the data: all 10 grip SPA rows show `final_state.selected:
null` on every attempt — never once did a catalog-item click land. `filter`
and `sort` — driven by semantic `<select>` and button controls that do pass
`gripIsCandidate` — moved off their defaults on 8 of 10 rows; spa-04 and
spa-05 show `filter: 'all', sort: 'none'`, i.e. defaults, so those two rows
are not clean evidence that the semantic controls worked and only the
item-click failed. On the other 8, the pattern holds: semantic controls
operated correctly, item selection never did. spa-08 additionally aborted on
"3 consecutive tool errors," the one row where the harness's own
retry-abort fired. browser-use's DOM serializer
picks up click listeners regardless of tag, which is why it clears 7 of the
same 10 fixtures.

## Where grip wins: speed and cost, on tasks both arms completed

Computed on the paired subset — task IDs where **both** arms succeeded — not
a per-arm median over all rows, because failures have a different wall/cost
profile and would bias an all-rows median. n=17 for wall (10 forms + 7
wizards; SPA contributes no paired rows because grip is 0/10 there).

The two statistics do **not** share a denominator: browser-use's
`total_cost_usd` is `null` on form-09 and form-10 (grip's is populated on
both), so cost is computed over n=15, wall over n=17. The null is
consistent with a killed CLI call inside a resumed segment (see Confounds).

```
-- total_wall_seconds (n=17) --
grip median: 106.6s   browser-use median: 1080.8s
ratio-of-medians (bu/grip): 9.98x
median-of-ratios (bu/grip): **8.42x**   range: 1.41x-30.50x

-- total_cost_usd (n=15) --
grip median: $0.636   browser-use median: $4.149
ratio-of-medians (bu/grip): 5.79x
median-of-ratios (bu/grip): **5.22x**
```

Bold marks the less flattering-to-grip statistic in each pair, per this
repo's convention (`RESULTS_BROWSERUSE.md`) — that is the one to quote. Both
statistics agree in direction here (unlike that file, where they disagreed
on one column): grip is faster and cheaper on every paired task where cost
was recorded; low end of the wall range is wizard-01, full per-task ratios
are in the reproduction script output below.

Spot figure, verified against the file (the number relayed before writing
this doc, $0.49, does not match the file and is not used):

| task | grip | browser-use |
|---|---|---|
| form-01 | 77.5s / $0.83 | 1087.2s / $3.69 |

## Wizards: 10/10 vs 7/10, different failure mode

grip: 10/10, one attempt each, no retries needed.

browser-use: 7/10, three failures now (wizard-06, wizard-08, wizard-09), all
the same pattern: stuck inside a shadow-DOM checkout step. `done_result` on
each reports progress through the shipping step (address, city, ZIP
entered) but never reaching payment/confirmation, on forms the harness log
shows sitting inside a shadow root. This is not "browser-use is worse at
wizards" as a general claim: the arms fail on different things. grip has
zero SPA capability and perfect wizard capability; browser-use has
decent-but-incomplete SPA capability and a recurring shadow-DOM failure
mode on multi-step forms — 3 of its 10 wizard runs, all the same shape.

## Confounds (all load-bearing, none of them footnotes)

- **Every fixture requires a `<select>`.** grip gained `select` as a tool
  hours before this run started. The corpus gates heavily on one interaction
  type grip only just supports; it is not a general-purpose sample of web
  tasks.
- **Fixtures are synthetic, authored in grip's own repo.** Treat this as a
  credibility limitation on the whole result, not a strength. No adversarial
  or third-party page design was involved.
- **Cost figures are not comparable to real API pricing.** No API key was
  available, so both arms ran through headless `claude -p` CLI sessions.
  Every LLM turn pays a fixed ~$0.07 CLI session overhead on top of token
  cost. The cost numbers above are as-billed by that CLI path, not
  content-only API cost; the harness in this run does not separately compute
  a content-only figure.
- **Tool-count asymmetry.** grip exposes 6 tools (snapshot, click, type,
  select, read, done). browser-use exposes roughly 15, including scroll and
  extract_content. A task that needs a tool grip lacks (e.g., scroll to
  reveal off-viewport content) registers in this table as a task failure,
  not as an efficiency loss — the two are conflated by a pass/fail metric.
- **Temperature was not controllable via the CLI on either arm.**
- **The browser-use arm ran in three resumed segments** across two harness
  hangs and a session restart. Results were resumed from saved rows via
  `--resume`, never re-run — no task was executed twice. Some rows carry a
  scar from this: browser-use's `total_cost_usd` is `null` on form-09 and
  form-10 (one retry attempt inside each recorded `cost_usd: null`, 0
  tokens, consistent with a killed CLI call), which is why the cost median
  above is n=15 while wall is n=17 rather than a clean shared denominator.
- **n=30 tasks, one run each, up to 3 attempts per task, no repeat runs.**
  There is no variance estimate on any number in this document. A single
  run of 30 tasks is a data point, not a distribution.

## What this changes

The single highest-value fix this data points to: **non-semantic clickable
element discovery**, e.g. via `DOMDebugger.getEventListeners` (CDP) or
equivalent, so `gripIsCandidate` can admit an element with an attached click
listener even without a semantic tag or ARIA role. That one change addresses
an entire failed category (SPA, 0/10 -> plausibly competitive with
browser-use's 7/10) without touching anything that currently works. Exposing
`click_at` as a registered tool would be a narrower, faster patch for the
same gap but pushes coordinate-targeting onto the model instead of fixing
discovery, and it is not a pure tool-registration change: `click_at` calls
`self._assert_not_safe("click_at")` (`grip/page.py:1240`), so it is gated
behind whatever safe-mode policy that assertion enforces and would need that
gate reviewed before exposure, not just a registry entry added.

## Reproducing

This doc's numbers were computed with a standalone script (not checked into
this repo per the constraints of this task — reads the newest
`benchmarks/corpus/results/raw_*.jsonl`). Per-category success counts are a
plain `Counter` over `(arm, category, success)`, omitted below for brevity;
the snippet below is the paired-subset median/ratio logic, which is the part
worth checking:

```python
import json, glob, statistics as st
f = sorted(glob.glob('benchmarks/corpus/results/raw_*.jsonl'))[-1]
rows = [json.loads(l) for l in open(f)]
grip = {r['task_id']: r for r in rows if r['arm'] == 'grip'}
bu = {r['task_id']: r for r in rows if r['arm'] == 'browseruse'}
paired = sorted(t for t in grip if t in bu and grip[t]['success'] and bu[t]['success'])
for field in ('total_wall_seconds', 'total_cost_usd'):
    pairs = [(grip[t][field], bu[t][field]) for t in paired]
    pairs = [(g, b) for g, b in pairs if g is not None and b is not None]  # drop nulls, don't patch
    g = [p[0] for p in pairs]; b = [p[1] for p in pairs]
    ratios = [b[i] / g[i] for i in range(len(pairs))]
    print(field, 'n=%d' % len(pairs), 'ratio-of-medians', round(st.median(b) / st.median(g), 2),
          'median-of-ratios', round(st.median(ratios), 2))
```

Output at time of writing (final, 60/60 rows):

```
FILE: benchmarks/corpus/results/raw_20260811-165327.jsonl ROWS: 60

grip         form     10/10   spa 0/10   wizard 10/10   overall 20/30 = 66.7%
browseruse   form     10/10   spa 7/10   wizard 7/10    overall 24/30 = 80.0%

paired (both succeeded) n=17

total_wall_seconds n=17 ratio-of-medians 9.98 median-of-ratios 8.42
total_cost_usd n=15 ratio-of-medians 5.79 median-of-ratios 5.22

form-01 spot check: grip 77.5s/$0.83, browseruse 1087.2s/$3.69
```
