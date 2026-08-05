# Reach evaluation

**Result: the reach hypothesis is falsified. On 23 pages where both arms could read
anything at all, static HTTP fetch recovered the content 23 times. The gap is zero,
in every category, including single-page apps.**

Run it yourself: `.venv/bin/python -m evaluation.run_reach`
Raw data: [`results.json`](results.json). Corpus: [`corpus.py`](corpus.py).

## What was being tested

`grip-search`'s pitch rested on *reach*: that driving a real browser retrieves content
a static-fetch vendor (Tavily, Exa) cannot see, because that content is rendered by
JavaScript. Cost and latency were already measured. Reach was the claim justifying
being 3–5x slower, and it had never been tested.

## Method

Both arms fetch the **same URL**. The only variable is the fetch mechanism, so nothing
about ranking, discovery or vendor pricing confounds the result.

- **browser arm** — grip: real Chrome, JS executed, `page.read()` extracts main content
- **static arm** — plain HTTP GET, tags stripped, entities decoded. What a static-fetch
  vendor's extractor has to work with.

Scoring avoids the obvious trap. Hand-written questions would let the author pick
examples that flatter the browser. Instead the marker is chosen by a **fixed rule**
applied identically to every page: the first 12 words of the longest content block the
browser recovered. If static fetch also got the page's substance, that text is in its
output too.

33 URLs across four categories, chosen to include cases the browser should *lose*:
server-rendered static sites, single-page apps, hybrid server/client pages, and
anti-bot-protected pages.

## Results

| category | n | browser | static | gap |
|---|---|---|---|---|
| static | 12 | 11 | 11 | **0** |
| spa | 9 | 7 | 7 | **0** |
| hybrid | 8 | 5 | 5 | **0** |
| protected | 4 | 0 | 0 | **0** |
| **total** | **33** | **23** | **23** | **0** |

Ten pages were unreadable by *both* arms: two dead URLs, four anti-bot walls
(StackOverflow, Google, Brave, LinkedIn), two pages where read-mode found no main
content, and two where the **browser** timed out and static fetch succeeded.

## Why the hypothesis failed

Modern documentation sites server-side render **because they need SEO**. react.dev,
vuejs.org, angular.dev, svelte.dev, tanstack.com, nextjs.org — every one ships its
content in the initial HTML payload. They are built with client-side frameworks, but
they are not client-*rendered* in the way the hypothesis assumed.

The premise confused *"built as an SPA"* with *"content only exists after JS runs"*.
For anything that wants Google traffic, the second is commercially impossible.

Where static fetch does fail, it fails because of **blocking**, not rendering — and
blocking defeats the browser too. All four protected pages beat both arms. A headless
browser is not a way around Cloudflare.

## The one thing the browser does better, measured

On the 23 pages where both arms succeeded, static fetch returns a **median 1.4x the
characters** the browser does for the same substance (range 0.5x–3.7x). The excess is
navigation, footers and inline script residue — text a model is billed for and cannot
use.

Real, but modest. And it reframes the token claim in the main README:

| baseline | grip snapshot is | relevant when |
|---|---|---|
| raw HTML | ~19x smaller | you would otherwise put HTML in the prompt |
| tag-stripped text | **~1.4x smaller** | comparing against a retrieval vendor |

Both are true. The second is the honest comparison against Tavily or Exa, because no
retrieval vendor sends raw HTML to a model. The 19x figure is only the right
comparison for an agent that would otherwise dump the DOM.

## What this means

**The product's central claim, as written, does not survive contact with measurement.**
"Reaches pages static fetch cannot" is not true for the modern documentation web, which
is the exact corpus a developer-tools retrieval product would serve.

Three honest positions remain, none of them "better reach":

1. **Structure and citations.** Static fetch yields an undifferentiated blob. grip
   yields ordered blocks with heading breadcrumbs, so a claim maps to a location. This
   is a real, demonstrable difference — and it is a *quality* claim, not a reach claim.
2. **Knowing when a fetch failed.** A static fetcher receiving a 200 consent wall
   returns junk indistinguishable from content. grip reports `page_error`. Untested
   here as a differentiator, and worth its own experiment.
3. **Interaction-to-reveal** (ticket 09) — content behind a click, pagination,
   infinite scroll. **This is the only place reach might still be real**, and it is
   exactly the tier this evaluation did not test, because grip does not implement it
   yet.

Ticket 09 was deferred on the reasoning that reach should be *proven* before being
*extended*. That reasoning holds, but the conclusion inverts: rendered-DOM reach is now
disproven, so if reach is to be the differentiator at all, interaction-to-reveal is no
longer optional — it is the entire hypothesis, and it needs its own evaluation before
anyone builds on it.

## Two measurement bugs found while building this

Both inflated the browser's score. Recording them because a benchmark that has never
been wrong has probably never been checked.

1. **Whitespace.** Stripping tags inserts a space at every tag boundary, so
   `<code>foo</code>bar` reads as `foo bar` statically and `foobar` through innerText.
   Collapsing whitespace instead of deleting it scored 10 pages as browser-only wins
   where static fetch had actually retrieved *more* text.
2. **HTML entities.** `->` is `-&gt;` in source. After tag-stripping, the normaliser
   folded the stray `gt` into the text as letters, breaking matches on any page
   containing code. Fixed with `html.unescape()`.

After the first fix the gap was 8. After the second it was 1. The last remaining "win"
turned out to be a dead URL where the browser read a 404 page and the static arm
correctly discarded the error. The true gap is zero.

## Limitations

- **33 URLs, one run, one residential IP.** Blocking behaviour especially is
  time- and IP-dependent.
- **The static arm is deliberately competent** — real browser UA, gzip, entity
  decoding. A naive fetcher would score worse, but so would a real vendor's.
- **English, developer-oriented corpus.** News, e-commerce, and social feeds are
  under-represented, and social feeds are where client-rendering is most real.
- **Marker matching tests content recovery, not answer quality.** A page can be
  recovered and still be ranked badly.
- **Nothing here tests interaction-to-reveal**, which is now the live hypothesis.
