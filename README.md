# grip

[![PyPI version](https://img.shields.io/pypi/v/grip-browser?color=black&style=flat-square)](https://pypi.org/project/grip-browser/)
[![Python](https://img.shields.io/pypi/pyversions/grip-browser?color=black&style=flat-square)](https://pypi.org/project/grip-browser/)
[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg?style=flat-square)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/84yk8btb9f-prog/grip-browser/test.yml?style=flat-square&label=tests)](https://github.com/84yk8btb9f-prog/grip-browser/actions)

**Token-efficient, CDP-native browser SDK for AI agents.**

Built directly on Chrome DevTools Protocol — no Playwright, no Puppeteer, no wrapper overhead.

```
pip install grip-browser
```

---

## The problem

Most browser tools give AI agents raw HTML or screenshots. Raw HTML is ~12,000 tokens per page. Screenshots are ~3,000 tokens. Both burn through context windows fast and slow your agent down.

## What grip does instead

grip gives your agent a semantic summary of what's on the page — just the interactive elements and visible text, structured for LLM consumption:

```
PAGE: Amazon.com
URL: https://www.amazon.com/

INTERACTIVE:
  [inp:0] "search here" (placeholder)
  [btn:1] "Go"
  [btn:2] "Sign in"
  [lnk:3] "Returns & Orders"

CONTENT:
  Delivering to New York — Shop deals in...
```

**~50 tokens per snapshot.** A full agent loop that would cost 200,000 tokens with raw HTML costs ~2,000 tokens with grip.

---

## Quick start

```python
import asyncio
from grip import Browser

async def main():
    async with Browser(headless=True) as browser:
        page = await browser.open("https://news.ycombinator.com")
        snapshot = await page.snapshot()

        print(snapshot.text_content)      # readable page text
        print(snapshot.elements)          # interactive elements only
        print(snapshot.tokens_estimated)  # ~50

asyncio.run(main())
```

## Full agent loop

```python
async with Browser(headless=True) as browser:
    page = await browser.open("https://amazon.com")
    await page.snapshot()               # build element index

    await page.type("search", "blue sneakers")
    await page.click("Go")              # fuzzy match — no selectors needed

    await page.snapshot()               # re-index after navigation
    data = await page.extract({"product": "str", "price": "str"})

    shot = await page.screenshot()      # JPEG, ~800 tokens for vision models
    shot.save("result.jpg")
```

## With an LLM (autonomous mode)

```python
from grip import Browser
from grip.adapters.anthropic import AnthropicAdapter

llm = AnthropicAdapter(api_key="sk-ant-...")

async with Browser(llm=llm, headless=True) as browser:
    result = await browser.run(
        goal="Find the cheapest blue sneakers under $80",
        url="https://amazon.com"
    )
    print(result.data)
    print(f"Used {result.tokens} tokens")
```

grip handles the snapshot → decide → act loop automatically. You just provide the goal.

---

## Why not Playwright or Puppeteer?

| | Playwright MCP | Puppeteer | grip |
|---|:---:|:---:|:---:|
| Tokens per snapshot | ~2,000 | ~2,000 | **~50** |
| Shadow DOM traversal | Partial | No | Full |
| Prompt injection guard | No | No | Yes |
| Typed error recovery | No | No | Yes |
| Element staleness detection | No | No | Yes |
| Pure CDP (no binary bloat) | No | No | Yes |
| Screenshot token tracking | No | No | Yes |

---

## Structured errors

Every error comes back as a typed `BrowserError` — not a bare string — so your agent can make decisions:

```python
from grip import GripError
from grip.errors.types import ErrorType, RecoveryAction

try:
    await page.click("checkout")
except GripError as e:
    match e.error.type:
        case ErrorType.CAPTCHA_REQUIRED:
            # recovery: ESCALATE_TO_HUMAN or VISION_FALLBACK
            await escalate(e.error.message)
        case ErrorType.RATE_LIMITED:
            # recovery: EXPONENTIAL_BACKOFF + RETRY
            await asyncio.sleep(30)
            await page.click("checkout")
        case ErrorType.AUTH_REQUIRED:
            # recovery: ESCALATE_TO_HUMAN
            raise NeedsLogin(e.error.message)
        case ErrorType.ELEMENT_STALE:
            # recovery: RE_SNAPSHOT + RETRY
            await page.snapshot()
            await page.click("checkout")
```

### Full error taxonomy

| Type | When | Suggested recovery |
|---|---|---|
| `ELEMENT_NOT_FOUND` | fuzzy match failed | re-snapshot, retry with different description |
| `ELEMENT_STALE` | element moved after navigation | re-snapshot |
| `ANTI_BOT_BLOCK` | Cloudflare, DDoS-Guard, 403 | rotate identity |
| `CAPTCHA_REQUIRED` | CAPTCHA challenge page | escalate to human |
| `RATE_LIMITED` | 429 Too Many Requests | exponential backoff |
| `AUTH_REQUIRED` | login wall | escalate to human |
| `ZERO_RESULTS` | page loaded, no matching content | retry, broaden query |
| `NETWORK_TIMEOUT` | navigation timed out | exponential backoff |
| `NAVIGATION_FAILED` | blank page / bad URL | retry |

---

## Shadow DOM

grip traverses shadow DOM trees automatically. Web components, Chrome extensions, custom elements — all discovered in the same snapshot:

```python
snapshot = await page.snapshot()
shadow_elements = [el for el in snapshot.elements if el.in_shadow_dom]
```

---

## Trace

Every action is recorded with timing and token cost:

```python
async with Browser() as browser:
    page = await browser.open("https://example.com")
    await page.snapshot()
    await page.click("Learn more")
    await page.screenshot()

print(browser.trace.total_tokens)   # total tokens used
browser.trace.to_jsonl("audit.jsonl")  # machine-readable audit log
```

---

## LLM adapters

grip ships with OpenAI and Anthropic adapters out of the box:

```python
from grip.adapters.openai import OpenAIAdapter
from grip.adapters.anthropic import AnthropicAdapter

llm = OpenAIAdapter(api_key="sk-...")         # gpt-4o, gpt-4-turbo, etc.
llm = AnthropicAdapter(api_key="sk-ant-...")  # claude-opus-4-7, etc.
```

Or bring your own by implementing the `LLMAdapter` protocol:

```python
from grip.adapters.base import LLMAdapter, LLMResponse

class MyAdapter:
    async def complete(self, messages, tools) -> LLMResponse:
        ...
```

---

## Requirements

- Python 3.11+
- Google Chrome (or Chromium) installed

grip finds Chrome automatically. Override with `CHROME_EXECUTABLE` env var.

---

## Install

```bash
pip install grip-browser

# with OpenAI support
pip install grip-browser[openai]

# with Anthropic support
pip install grip-browser[anthropic]
```

---

## License

MIT
