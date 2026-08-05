# Hacker News Show HN Post — grip-browser

## Title

Show HN: grip-browser – 50-token browser snapshots for AI agents (vs ~12k raw HTML)

## Body

I build LLM agents and kept running into the same ceiling: every time an agent needs to look at a webpage, it burns 10–15k tokens on raw HTML that's 95% noise — nav bars, inline scripts, aria boilerplate, deeply nested divs. For multi-step browsing tasks that cost adds up fast and hits context limits.

grip-browser is my attempt at a different abstraction. Instead of dumping the DOM, it uses Chrome DevTools Protocol directly to extract a semantic snapshot: visible text, interactive elements (buttons, inputs, links), and their bounding boxes. Measured across 8 real pages, a median of 77,588 tokens of raw HTML comes out at 2,018 tokens with grip — a 19x reduction, ranging from 3x on a trivial page to 95x on a heavy SPA. The snapshot is enough for an agent to decide what to click or type next without seeing the full DOM.

A few things I think are worth calling out:

**No Playwright/Puppeteer.** grip talks CDP directly, so there's no Node.js process in the loop. You get a lighter dependency footprint and can run it from pure Python.

**Shadow DOM traversal.** Most snapshot tools miss content inside shadow roots. grip walks them, so things like web component UIs aren't invisible to the agent.

**Typed error taxonomy.** When something goes wrong, agents get structured errors — `CAPTCHA_REQUIRED`, `RATE_LIMITED`, `AUTH_REQUIRED`, `NAVIGATION_FAILED` — instead of raw exceptions. This matters in practice: an agent that knows it hit a CAPTCHA can route differently than one that just sees a timeout.

**LLM adapters.** There are thin wrappers for Anthropic and OpenAI so the snapshot plugs into tool-use flows without manual formatting.

Current state: v0.2.0, installable via `pip install grip-browser`. The core snapshot flow is solid. Session persistence ships in this release — `save_session`/`load_session` carry cookie and auth state across instantiations. Known gap: requires Chrome installed locally (no bundled browser). There are rough edges on dynamic SPAs that do heavy client-side rendering after load.

GitHub: https://github.com/84yk8btb9f-prog/grip-browser

Feedback I'm actually looking for: Is the 50-token snapshot too lossy for your use case? Are there page structures where the semantic extraction breaks down? And is the typed error taxonomy the right set of errors, or are there failure modes I'm missing from real agent deployments?
