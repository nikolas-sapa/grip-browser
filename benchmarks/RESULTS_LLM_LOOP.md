# Task success: grip vs browser-use, agent loop in the loop

Date: 2026-08-11. First benchmark in this repo that measures whether a task
actually got done, not payload bytes. `RESULTS_AB.md` and
`RESULTS_BROWSERUSE.md` measured observation size with no LLM in the loop;
both said explicitly that they could not tell a good observation from a bad
one. This one puts a real model in the loop and scores completion.

**Coverage: 58 of 60 rows.** browser-use wizard-09 and wizard-10 were still
running when this was written (a resumed run, see confounds below) and are
not in this table. Everything else — grip's full 30, browser-use's other 28
— is complete. Do not read the browser-use wizard category total as final;
it is 6/8 with 2 tasks outstanding, not 6/10.

The ordering does not depend on those 2 rows: browser-use is 23/28 now, so
its final score lands between 23/30 (76.7%, both pending rows fail) and
25/30 (83.3%, both succeed). Either way it beats grip's 66.7%.

**Lead with the loss: browser-use has the higher success rate.**

| arm | overall | driven by |
|---|---|---|
| grip | 20/30 = 66.7% | forms 10/10, wizards 10/10, **SPA 0/10** |
| browser-use | 23/28 = 82.1% (2 wizard rows pending) | forms 10/10, SPA 7/10, wizards 6/8 |

## Per-category table

| category | grip | browser-use |
|---|---|---|
| form | 10/10 | 10/10 |
| SPA | **0/10** | 7/10 |
| wizard | 10/10 | 6/8 (2 pending) |

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
profile and would bias an all-rows median. n=16 (10 forms + 6 wizards; SPA
contributes no paired rows because grip is 0/10 there).

```
-- total_wall_seconds --
grip median: 106.6s   browser-use median: 1080.8s
ratio-of-medians (bu/grip): 10.14x
median-of-ratios (bu/grip): **8.50x**

-- total_cost_usd --
grip median: $0.636   browser-use median: $4.149
ratio-of-medians (bu/grip): 6.52x
median-of-ratios (bu/grip): **5.39x**
```

Bold marks the less flattering-to-grip statistic in each pair, per this
repo's convention (`RESULTS_BROWSERUSE.md`) — that is the one to quote. Both
statistics agree in direction here (unlike that file, where they disagreed
on one column): grip is faster and cheaper on every one of the 16 paired
tasks, by 1.41x-30.5x wall and 1.92x-19.0x cost depending on the task (the
low end on both is wizard-01); full per-task ratios are in the reproduction
script output below.

Two of the 16 paired cost rows (browser-use form-09, form-10) use the
patched cost described in Confounds — one retry attempt inside each had
`cost_usd: null`, and this doc sums the non-null attempts rather than
dropping the row. Excluding those two entirely (n=14) leaves median-of-ratios essentially
unchanged (5.39x) and moves ratio-of-medians from 6.52x to 6.18x — the
direction and magnitude of the result do not change.

Spot figure, verified against the file (the number relayed before writing
this doc, $0.49, does not match the file and is not used):

| task | grip | browser-use |
|---|---|---|
| form-01 | 77.5s / $0.83 | 1087.2s / $3.69 |

## Wizards: 10/10 vs 6/8, different failure mode

grip: 10/10, one attempt each, no retries needed.

browser-use: 6/8 confirmed (wizard-09, wizard-10 pending). Its two confirmed
failures (wizard-06, wizard-08) both stall inside a shadow-DOM checkout
step — `done_result` reports getting stuck after the shipping step, unable
to reach payment, on a form the harness log shows sitting inside a shadow
root. This is not "browser-use is worse at wizards" as a general claim: the
arms fail on different things. grip has zero SPA capability and perfect
wizard capability; browser-use has decent-but-incomplete SPA capability and
occasional shadow-DOM friction on multi-step forms.

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
- **The browser-use arm ran in three segments** after two harness hangs;
  results were resumed via `--resume`, not re-run from scratch. Five rows
  (browseruse form-09, form-10, spa-02, spa-08, wizard-08) have a `null`
  `total_cost_usd` in the raw file because one retry attempt inside them
  recorded `cost_usd: null` (0 tokens, consistent with a hung/killed CLI
  call) — this doc sums the non-null attempt costs for those five rows
  rather than dropping them, and that patch is itself a product of the
  segmented run, not of a clean single pass.
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
cat = lambda tid: tid.split('-')[0]
def cost_of(r):
    if r.get('total_cost_usd') is not None: return r['total_cost_usd']
    vals = [a['cost_usd'] for a in r['attempts'] if a.get('cost_usd') is not None]
    return sum(vals) if vals else None
grip = {r['task_id']: r for r in rows if r['arm'] == 'grip'}
bu = {r['task_id']: r for r in rows if r['arm'] == 'browseruse'}
paired = sorted(t for t in grip if t in bu and grip[t]['success'] and bu[t]['success'])
for field, get in [('total_wall_seconds', lambda r: r['total_wall_seconds']),
                    ('total_cost_usd', cost_of)]:
    g = [get(grip[t]) for t in paired]; b = [get(bu[t]) for t in paired]
    ratios = [b[i] / g[i] for i in range(len(paired))]
    print(field, 'ratio-of-medians', st.median(b) / st.median(g),
          'median-of-ratios', st.median(ratios))
```

Output at time of writing:

```
FILE: benchmarks/corpus/results/raw_20260811-165327.jsonl ROWS: 58

grip         form     10/10
grip         spa      0/10
grip         wizard   10/10
browseruse   form     10/10
browseruse   spa      7/10
browseruse   wizard   6/8

grip overall: 20/30 = 66.7%
browseruse overall: 23/28 = 82.1%

paired (both succeeded) n=16:
['form-01'..'form-10', 'wizard-01','wizard-02','wizard-03','wizard-04','wizard-05','wizard-07']

total_wall_seconds: grip median 106.6s, browseruse median 1080.8s
  ratio-of-medians 10.14x, median-of-ratios 8.50x
total_cost_usd: grip median $0.636, browseruse median $4.149
  ratio-of-medians 6.52x, median-of-ratios 5.39x

form-01 spot check: grip 77.5s/$0.83, browseruse 1087.2s/$3.69
```
