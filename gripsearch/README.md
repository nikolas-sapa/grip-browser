# grip-search

Agent-grade retrieval on top of [grip](../README.md). A question in, ranked cited
passages out — by driving a real browser against real pages.

Distribution `grip-search`, import `gripsearch`.

```python
from gripsearch import Retriever, BraveSource

async with Retriever(BraveSource(api_key=...)) as r:
    result = await r.search("how does asyncio.gather handle exceptions")

for p in result.passages:
    print(p.text)
    print(f"  — {p.url} {p.citation}")

for f in result.failures:      # blocked or unreachable sources, never silently dropped
    print("failed:", f)
```

## What it claims

Not "faster than Tavily" — measured, it is 3–5x slower. Real page loads cost real
seconds and no amount of engineering removes that.

- **Same or lower cost — for text-oriented content.** ~$0.025/query before proxy
  bandwidth, versus ~$0.049 for an equivalent Tavily path. The browser is not where
  the money goes; the LLM read is, and that is identical either way.

  Measured with residential proxies and `block_resources=True`: documentation
  $0.034, blogs $0.035, reference $0.044 — all under Tavily. **News ($0.118) and
  e-commerce ($0.112) are roughly 2.4x more expensive**, because proxies bill per
  gigabyte and those pages are ~3 MB. Point this at media-heavy sites and the
  economic argument inverts. See [`evaluation/PAGE_WEIGHT.md`](../evaluation/PAGE_WEIGHT.md).
- ~~**Better reach.**~~ **Measured, and it does not hold.** Across 33 URLs, static
  fetch recovered the content on every page either arm could read — 23/23, gap zero,
  including SPAs, because documentation sites server-render for SEO. See
  [`evaluation/`](../evaluation/). Where static fetch fails it fails on *blocking*,
  and blocking defeats a headless browser too.
- **Real citations.** Every passage carries a URL plus a block id and heading trail,
  not just a document.

## Pipeline

1. `source.find(query, limit=8)` → candidates
2. Fetch all concurrently through one grip `Browser`, 15s per page
3. Drop sources whose `page_error` is set — before spending a token on them
4. `page.read()` each survivor → citable blocks
5. BM25 rank across blocks, dedup near-duplicates
6. Return passages, with failures attached

## Design notes

**Discovery is rented, extraction is owned.** `CandidateSource` has one method.
`BraveSource` is the only real implementation — SERP scraping was measured and
returns zero extractable results on every engine tried, so no scrape implementation
ships. One that returned nothing would get reached for during an outage and fail
silently.

**Ranking is BM25, not embeddings.** Embeddings add a model call and an index to a
pipeline already dominated by the LLM read cost, and nothing measured says lexical
ranking is the accuracy bottleneck. Revisit when a reach evaluation exists.

**Failures are reported, never dropped.** A blocked source appears in
`result.failures`. If every source fails, `search()` raises `NoUsableSources` with
them attached rather than returning an empty result that reads like "nothing found".

**Stealth defaults on here**, unlike grip. A retrieval layer fetching public pages
has no reason to announce itself as automation; a general-purpose SDK does.

## Not in v1

Interaction-to-reveal (pagination, "show more", infinite scroll), proxies, answer
synthesis, caching, MCP/HTTP surface. See the spec for why.
