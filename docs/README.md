# docs

Index of documentation across the repo. Not a rewrite of anything below — one honest
line per file, and a note where something isn't documented at all.

## Get started

- [`../README.md`](../README.md) — the main doc. Install, quick start, full agent
  loop, read mode, challenges/CAPTCHAs, autonomous LLM mode, structured errors,
  shadow DOM, trace, LLM adapters, requirements, CLI. Start here; everything else
  is a supplement to it.
- [`../examples/quickstart.py`](../examples/quickstart.py) — smallest possible
  working example: open a page, snapshot it, print it. Zero edits needed, just
  `python examples/quickstart.py` with Chrome installed.

## Use it as an MCP server

- [`mcp.md`](mcp.md) — `grip-mcp` stdio server setup: install, the eleven
  non-LLM tools plus the LLM-backed `run` tool, client config. Does not cover
  the Python SDK itself (see main README) or MCP tool-call examples beyond setup.

## Measurements: how the numbers were produced

Two separate measurement trees, not consolidated into one report.

- [`../benchmarks/`](../benchmarks/) — payload-size and task-success benchmarks
  against Playwright MCP, Puppeteer, and browser-use. Result files:
  - [`RESULTS_COMPETITORS.md`](../benchmarks/RESULTS_COMPETITORS.md) — grip vs
    Playwright MCP vs Puppeteer, snapshot token size. This is the source for the
    headline numbers in the main README.
  - [`RESULTS_AB.md`](../benchmarks/RESULTS_AB.md) — three-way token A/B, no LLM
    in the loop.
  - [`RESULTS_BROWSERUSE.md`](../benchmarks/RESULTS_BROWSERUSE.md) — grip vs
    browser-use, observation payload size only.
  - [`RESULTS_LLM_LOOP.md`](../benchmarks/RESULTS_LLM_LOOP.md) — grip vs
    browser-use with an actual agent loop, task success rather than payload
    bytes. Supersedes the size-only claims in the two files above for "does the
    task get done" questions; those two files say so themselves.
  - [`RESULTS_CHALLENGES.md`](../benchmarks/RESULTS_CHALLENGES.md) — challenge
    (CAPTCHA/slider/etc.) classification accuracy and solve rate, with a
    post-fix update logged in the same file.
- [`../evaluation/`](../evaluation/) — hypothesis-driven evaluations, each with
  its own result markdown plus raw `*_results.json`:
  - [`evaluation/README.md`](../evaluation/README.md) — reach evaluation.
    **Falsified**: static HTTP fetch matched grip's browser-rendered recovery on
    all 23 comparable pages of a 33-page corpus.
  - [`evaluation/INTERACTION.md`](../evaluation/INTERACTION.md) —
    interaction-to-reveal (`page.read(interact=True)`). Holds narrowly on a
    small, not-yet-generalized corpus.
  - [`evaluation/PAGE_WEIGHT.md`](../evaluation/PAGE_WEIGHT.md) — whether the
    per-query cost model survives real page weight. Holds for text-oriented
    content, fails for media-heavy content.
  - [`evaluation/SILENT_FAILURE.md`](../evaluation/SILENT_FAILURE.md) — whether
    grip surfaces failures a static fetcher would silently swallow. Mixed:
    explicit `page_error` never fired in this run; a different signal (short
    output) partially covered the gap.
- [`research/proxy-pricing.md`](research/proxy-pricing.md) — research note, not
  a benchmark: does proxy bandwidth cost break the cost model. Conditional yes
  for this project's own light pages, no for median-web-page weight.

Unmeasured, stated plainly: proxy pricing under load, cross-browser behavior
(everything above is Chrome/Chromium only), and interaction-to-reveal beyond the
small corpus in `INTERACTION.md`.

## Contribute

- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — dev setup, editable install, test
  and lint commands.
- [`../CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md) — Contributor Covenant.

## Security

- [`../SECURITY.md`](../SECURITY.md) — how to report a vulnerability privately
  and what to include.

## Changes

- [`../CHANGELOG.md`](../CHANGELOG.md) — release-by-release changes, Keep a
  Changelog format.
