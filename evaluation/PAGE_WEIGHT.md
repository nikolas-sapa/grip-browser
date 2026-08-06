# Page weight and the cost model — measured

**Result: the cost claim holds for text-oriented content and fails for media-heavy
content, and resource blocking is what makes the difference. With images, fonts and
media blocked, documentation ($0.034), blogs ($0.035) and reference pages ($0.044)
all come in under Tavily's $0.049 per query. News ($0.118) and e-commerce ($0.112)
do not — they are roughly 2.4x more expensive, and no amount of blocking rescues
them.**

Run it yourself: `.venv/bin/python -m evaluation.run_page_weight`
Raw data: [`page_weight_results.json`](page_weight_results.json). Corpus:
[`page_weight_corpus.py`](page_weight_corpus.py).

## Why this was measured

[`docs/research/proxy-pricing.md`](../docs/research/proxy-pricing.md) concluded the
per-query cost model survives residential proxies — but only because this project's
test pages averaged ~0.50 MB. Substitute the HTTP Archive median page (2.41 MB) and
the same query costs twice Tavily. Proxies bill per gigabyte, so page weight *is* the
cost model.

That 0.50 MB came from a developer-documentation corpus assembled to test something
else entirely. Nobody had checked whether it represents what a user of this tool
would actually fetch. It was the single unvalidated input, and it swung the headline
conclusion by ~6x.

## Method

Real bytes over the wire, not estimates: a CDP `Network.loadingFinished` listener
sums `encodedDataLength` across every request a page makes. That is what a proxy
bills for. HTML length would miss images, CSS, fonts and JS, which are most of the
weight.

Two arms per URL — **full** (a normal fetch) and **blocked** (images, fonts and media
suppressed via `Network.setBlockedURLs`, which is standard practice for automated
fetching). 50 URLs across five categories, ~10 each.

Cost arithmetic uses 8 pages per query and $4/GB residential proxy pricing, both
taken from the existing cost model and proxy research rather than re-derived:
`total = $0.025 base + (8 × MB ÷ 1024 × $4)`.

## Results

Medians. `n` is full/blocked pages that loaded successfully; failures are excluded
from the medians rather than counted as zero.

| category | n | full MB | blocked MB | full $/query | blocked $/query | beats Tavily? |
|---|---|---|---|---|---|---|
| docs | 9/10 | 0.64 | 0.27 | $0.045 | $0.034 | yes |
| blog | 8/8 | 1.00 | 0.31 | $0.056 | $0.035 | yes |
| reference | 8/8 | 0.82 | 0.62 | $0.051 | $0.044 | yes |
| news | 8/8 | 3.53 | 2.98 | $0.135 | $0.118 | **no** |
| ecommerce | 7/5 | 4.56 | 2.79 | $0.167 | $0.112 | **no** |

Tavily's comparable path is $0.049.

## What this changes

**1. Resource blocking moves from "nice to have" to load-bearing.** Without it only
documentation clears the bar; blogs and reference pages both lose. With it, three of
five categories win. grip did not support blocking when this was measured — it was
added in the same release as a result (`Browser(block_resources=True)`, opt-in).

**2. The original 0.50 MB figure was optimistic even for its own category.** Measured
properly, documentation pages are 0.64 MB unblocked. The favourable conclusion in the
proxy research survives, but by less margin than it claimed.

**3. The product has a corpus boundary, and it should be stated rather than
discovered by a user.** This is a retrieval tool for text-oriented content —
documentation, references, articles. Pointed at news or shopping it costs roughly
2.4x what a static-fetch vendor costs, and the central economic argument inverts.

## Limitations

- One run, one residential connection, one geography. Ad-heavy pages in particular
  vary enormously by location and by what ad auctions serve at that moment.
- Medians over ~8-10 pages per category. Enough to separate 0.3 MB from 3 MB; not
  enough to distinguish 0.62 from 0.82.
- Two pages failed to load and are excluded. E-commerce lost more pages under
  blocking (5 of 10 usable) than unblocked (7 of 10) — worth noting, since a category
  that resists automated fetching is also a category this tool serves badly.
- Blocking is measured as pure saving here. It does change what the browser renders,
  and a page whose content depends on an image (a chart, a scanned document) loses
  that content entirely. Nothing in this corpus tested that failure mode.
- Proxy pricing is inherited from `docs/research/proxy-pricing.md`, not re-verified.
  Prices change.
