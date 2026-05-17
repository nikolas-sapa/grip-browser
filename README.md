# grip

A Python SDK that gives AI agents a token-efficient, secure way to interact with any website.
Built directly on Chrome DevTools Protocol — no Playwright overhead.

## Install

```
pip install grip-browser
```

## Quick start

```python
from grip import Browser

# Simple: let grip handle everything
browser = Browser(llm=my_llm)
result = await browser.run("Find cheapest blue sneakers under $80", url="amazon.com")
print(result.data)
print(result.tokens)

# Precise: full control for your agent loop
async with Browser() as browser:
    page = await browser.open("https://amazon.com")
    state = await page.snapshot()
    await page.click("search bar")
    await page.type("search bar", "blue sneakers")
    await page.press("Enter")
    data = await page.extract({"results": "list", "count": "int"})
```

## Why grip

| | Playwright MCP | grip |
|---|---|---|
| Tokens per snapshot | ~2,000 | ~80 |
| Shadow DOM | Partial | Full |
| Prompt injection guard | No | Yes |
| Typed error recovery | No | Yes |
| Element staleness detection | No | Yes |

## Structured errors

Instead of bare string errors, grip returns typed `BrowserError` objects:

```python
from grip import BrowserError, ErrorType, RecoveryAction

# Every error has: type, message, confidence, and recovery actions
# ErrorType.ELEMENT_STALE     → re_snapshot + retry
# ErrorType.ANTI_BOT_BLOCK    → rotate_identity
# ErrorType.AUTH_REQUIRED     → escalate_to_human
# ErrorType.NETWORK_TIMEOUT   → exponential_backoff
```

## LLM adapters

```python
from grip import Browser
from grip.adapters.openai import OpenAIAdapter
from grip.adapters.anthropic import AnthropicAdapter

llm = AnthropicAdapter(api_key="sk-ant-...")
browser = Browser(llm=llm)
```

Works with any LLM implementing the `LLMAdapter` protocol.

## License

MIT
