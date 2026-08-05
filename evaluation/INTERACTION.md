# Interaction-to-reveal evaluation

**Result: the hypothesis holds, narrowly. `page.read(interact=True)` recovered real
content beyond plain `read()` on 4 of 4 verified positive cases (Stripe's API
reference pages), and on 0 of 9 control/accordion pages it was expected not to — plus
one unplanned false positive on a page I had labelled a plain control. But the corpus
that produces a positive result at all is small and specific: of ~25 real-world
candidates hand-probed while building this corpus (pricing-page FAQs, GitHub PR
diffs, forum threads, Wikipedia navboxes, video descriptions, native `<details>`
docs), only one pattern — expandable object-schema attributes on API reference pages
— reliably gated content behind a click that this heuristic can find. Every "the
answer is hidden until you click" accordion tried gates nothing, because it's built
with CSS height animation, not DOM removal, so `read()` without interaction already
sees the text.**

Run it yourself: `.venv/bin/python -m evaluation.run_interaction`
Raw data: [`interaction_results.json`](interaction_results.json). Corpus:
[`interaction_corpus.py`](interaction_corpus.py).

## What was being tested

The reach evaluation ([`README.md`](README.md)) falsified rendered-DOM reach: static
fetch matched the browser on all 23 comparable pages. It named interaction-to-reveal
as the one remaining place reach could still be real, and flagged that
`page.read(interact=True)` had shipped in 0.3.0 with no evaluation. This measures it:
on pages whose content is genuinely gated behind a click or scroll, how much more
does `read(interact=True)` recover than plain `read()` and than a static fetch?

## Method

Each URL is read three ways on the same tab: `read()`, then `read(interact=True)`,
then a static HTTP fetch (`static_fetch()`, reused unmodified from `run_reach.py`).
Gain is a block-set diff — blocks present after interaction whose text wasn't present
before — not a raw length threshold, because a length delta alone can't distinguish
real new content from layout jitter between two `Runtime.evaluate` calls a few
hundred ms apart. A page only counts as "gained" if it cleared both a 50-character
floor *and* added at least one new block.

The marker for each gain is the first 12 words of the longest newly-revealed block —
a fixed rule, not hand-picked — checked against the static fetch to see whether the
"reveal" was actually reachable without a browser at all.

**Corpus** (14 pages, `interaction_corpus.py`):
- `api_reference` (4) — Stripe API object pages. Verified by hand before being added:
  printed the actual new block text from a `_reveal_step()` call and read it, not
  just trusted a character count (see below).
- `accordion_ui` (5) — pages with visible FAQ/accordion controls that the click
  heuristic does match and click, included specifically to stress-test for false
  positives on pages that *look* like they should gate content.
- `control` (5) — ordinary pages with no interaction affordance at all.

Getting to that list took probing ~25 candidates that didn't make it in, because
most "reveal" UI on the modern web turned out not to gate anything from `read()`:
Wikipedia collapsible navboxes, GitHub PR diffs ("Load diff" doesn't match the click
phrase list), IMDb/Amazon "read more" truncation, old.reddit "load more comments",
YouTube description "show more", six SaaS pricing-page FAQ accordions (Notion,
Slack, GitHub, Squarespace, HubSpot, Mailchimp), a GitHub docs FAQ page, and several
docs sites' troubleshooting pages. All of these render the "collapsed" text into the
DOM up front and hide it with CSS height/max-height/opacity, so `.innerText` — what
`READ_CONTENT_JS` reads — already contains it before any click.

## Results

| category | n | gained | median +chars | median +ms (interact - none) |
|---|---|---|---|---|
| api_reference | 4 | **4/4** | +3,221 | +48ms |
| accordion_ui | 5 | 0/5 | +0 | +1,082ms |
| control | 5 | 1/5* | +0 | +1,046ms |

\* one unplanned false positive, detailed below — not a page picked to test gating,
one I believed had no interaction affordance at all.

### The 4 verified positives

All four are Stripe API reference pages (`charges`, `customers`, `payment_intents`,
`subscriptions`) with nested-object schemas collapsed behind a "Show child
attributes" toggle. Clicking it adds real DOM nodes with real field documentation —
verified by printing the actual new blocks before trusting the character count, e.g.
`charges/object` gained 29 new blocks including:

> "The full statement descriptor that is passed to card networks, and that is
> displayed on your customers' credit card and bank statements..."

None of the four markers were present in the static fetch (`marker_in_static: false`
on all 4) — this is a genuine reach case, not a static-fetch failure to look hard
enough. Gains ranged 2,196–4,348 characters (12–15% of the page).

### The one unplanned false positive: github.com/sindresorhus/awesome

Picked as a plain control (a long static README with no accordion). It gained 473
characters and 13 new blocks. Printing the actual new text showed it was not FAQ or
article content — it was a block of recent commit messages, sponsor/funding links,
and a contributor count, e.g. `"Fix: Prevent repo linter from crashing on
deletion-only PRs (#4283)"`, `"opencollective.com/sindresorhus"`. The click heuristic
matched something on GitHub's repo page (its phrase list includes bare "next", which
is common on paginated widgets) and that click triggered a client-side view change
that surfaced a metadata panel `READ_CONTENT_JS`'s main-content scorer picked up as
part of the page. This is a real, reproducible effect (also not in the static fetch:
`marker_in_static: false`), but it's incidental sidebar/commit-history metadata, not
the article content a reader came for. Reported because it contradicts my own
corpus label, not because it was found by the eval design — I picked this URL
believing it had no reveal affordance, and it did.

### The 5 accordion_ui pages: zero gain, despite clicking

`_reveal_step()` did click something on every one of the 5 (verified separately,
outside the corpus run, by instrumenting the click return value directly). On
`slack.com/pricing`, for example, the first `[aria-expanded="false"]` element in DOM
order was not the FAQ accordion at all — it was a language/nav dropdown button
(`"機能"`, a features-menu toggle) that happens to appear before the FAQ section in
document order. The heuristic clicks the *first* match, not the most relevant one, so
on pages with unrelated `aria-expanded` elements earlier in the DOM it can spend its
one interaction on the wrong control. On the other four, the FAQ text was already
present pre-click (CSS accordion, not DOM-conditional), so even a correctly-targeted
click would have gained nothing.

## Cost

Mean `read()`: 24ms. Mean `read(interact=True)`: 830ms — **34x**, driven almost
entirely by pages where nothing was found to reveal. The interaction loop's poll step
(`_await_block_growth`) waits up to a full second for block-count growth before
concluding a click did nothing; when a click genuinely reveals content the growth is
detected almost immediately (the 3 non-outlier Stripe pages cost 38–48ms extra), but
when it doesn't, the full ~1s poll window is spent every time before the plateau
check breaks the loop after its first (only) iteration. One outlier
(`charges/object`, +1,103ms despite gaining content) doesn't fit this pattern and is
unexplained — possibly cold-start/warm-up cost from being first in the run, not
interaction cost; flagged rather than folded into the average silently.

Practically: on pages that don't gate anything (the large majority, per this and the
probing above), `interact=True` is paying **~1 second per page for nothing**, every
time, because "found nothing to click, waited anyway" is indistinguishable up front
from "found nothing to click."

## Honest conclusion

The hypothesis — that interaction-to-reveal is the one place a browser might still
see content static fetch cannot — **holds on the narrow corpus that could be built to
test it, and the corpus itself is the finding.** Confirmed genuine gating exists,
verified by hand, reproducible across 4 pages of one specific real-world pattern
(expandable schema attributes on API docs). It does not hold as a general claim about
"the web" the way reach was originally pitched: of roughly 25 real pages tried while
building this corpus, only that one pattern gated anything a reader would call
content. FAQ/pricing accordions — the more common candidate — gate nothing, because
they are built with CSS, not conditional rendering. If this becomes a product claim,
it should be scoped to "recovers content behind API-doc-style expandable schemas and
similar DOM-conditional reveals," not "recovers content behind accordions" or
"handles interactive pages" generally — those specific, more common UI patterns were
tested here and came back negative.

The cost is real and currently paid on every page regardless of whether anything is
found: ~1 second overhead, unconditionally, driven by a fixed poll timeout rather
than an early-exit on "found no candidate to click." That's a mechanism-level
optimization opportunity (skip the poll entirely when `_reveal_step()` didn't click
anything and there's nothing to scroll further), not a finding about the hypothesis.

## Limitations

- **14 pages, one run, one residential IP.** Smaller than the reach corpus (33) and
  the silent-failure corpus (12) because verified positives were hard to find, not
  because fewer were tried — see the ~25 rejected candidates above.
- **The false-positive count (1) is a lower bound on surprises, not an upper bound.**
  It was found by inspection because the corpus was small enough to eyeball every
  row; a larger `control` set would likely surface more incidental client-side view
  changes like the GitHub one.
- **`max_interactions=3` default was never actually exercised** — every page in this
  corpus plateaued or gained on the first click; nothing here tests whether a second
  or third interaction step recovers anything further (e.g. multi-level infinite
  scroll, or an accordion with several independent expanders that each need their own
  click). `SCROLL_BOTTOM_JS` (the no-button fallback) was likewise never exercised —
  every page in this corpus had a matching click target or nothing to reveal at all,
  never neither.
- **Single vendor for the positive category.** All 4 verified gains are Stripe API
  docs; other API-doc platforms (Redoc, ReadMe.io, Swagger UI) with similar
  expandable-schema UI were not tested and may or may not use the same reveal
  pattern.
- **The cost outlier on `charges/object` (+1,103ms) is unexplained**, not folded into
  a clean narrative — flagged rather than hidden.
