# grip — Design Specification

**Date:** 2026-05-17  
**Status:** Approved  
**Package name:** `grip-browser` (`pip install grip-browser`)  
**Repo:** `~/dev/agentbrowser`

---

## Overview

`grip` is a Python SDK that gives AI agents a precise, token-efficient, and secure way to read and interact with any website. It is built on Chrome DevTools Protocol (CDP) directly — no Playwright intermediary for data extraction — giving full control over exactly what data flows to the LLM.

The primary design constraint is token efficiency: every architectural decision must minimize the tokens consumed per agent action without sacrificing accuracy or safety.

---

## Problem Statement

Every existing browser interaction tool for AI agents was designed for humans automating tasks, not agents executing at machine scale. The result:

- Playwright MCP burns 114K tokens per 10-step task (tool definitions alone cost 13,700 tokens)
- DOM-based tools are blind to Shadow DOM and canvas-heavy apps (Figma, Google Sheets)
- No tool sanitizes page content against prompt injection before LLM ingestion
- Error responses are unstructured strings — the LLM must guess how to recover
- Element references go stale in dynamic SPAs; no tool implements snapshot versioning

`grip` solves all five problems from first principles.

---

## Architecture

Four layers beneath the Developer API, each with a single responsibility. Data flows top-to-bottom; the LLM only ever sees output from Layer 1.

```
┌─────────────────────────────────────┐
│          Developer API              │  ← Agent talks here
│  run() · snapshot() · click()       │
│  type() · extract() · observe()     │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│       Layer 1: Compression Engine   │  ← Token-first representation
│  • DOM → compact semantic summary   │
│  • Element cache (avoid re-reads)   │
│  • Snapshot versioning              │
│  • Differential updates             │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│    Layer 2: Security & Sanitization │  ← Every page passes through this
│  • Strip hidden elements            │
│  • Detect prompt injection patterns │
│  • Scope context to task region     │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│    Layer 3: Error Recovery          │  ← Typed errors, not strings
│  • Classify failure type            │
│  • Confidence score                 │
│  • Prescribed recovery actions      │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│    Layer 4: CDP Engine              │  ← Direct Chrome protocol
│  • WebSocket to Chrome/Chromium     │
│  • Full Shadow DOM traversal        │
│  • Surgical data extraction         │
│  • Vision fallback hook (V2)        │
└──────────────┬──────────────────────┘
               │
         ┌─────▼─────┐
         │  Chrome /  │
         │  Chromium  │
         └────────────┘

Cross-cutting: Observability Trace (all layers emit structured events)
```

---

## Developer API

### High-level (simple entry point)

```python
from grip import Browser

browser = Browser(llm=my_llm)

result = await browser.run(
    "Find the cheapest blue sneakers under $80",
    url="amazon.com"
)

print(result.data)    # structured output matching task
print(result.trace)   # full action-by-action trace
print(result.tokens)  # total tokens consumed
```

`run()` accepts any LLM that implements a minimal interface (see LLM Adapter below). It runs an internal action loop using the primitive API, respects error recovery, and returns a structured result.

### Primitive API (full control)

```python
from grip import Browser

browser = Browser()
page = await browser.open("https://amazon.com")

# Get a compact semantic summary of the page — not raw HTML
state = await page.snapshot()
# state.elements: list of interactive elements with stable refs
# state.text: sanitized readable content
# state.version: snapshot version number
# state.tokens: tokens this snapshot would consume

# Act using semantic descriptions — not CSS selectors
await page.click("search bar")
await page.type("blue sneakers under $80")
await page.press("Enter")

# Wait for navigation and re-snapshot
state = await page.snapshot()

# Extract structured data
data = await page.extract({
    "results": "list[Product]",
    "total_count": "int"
})

# Observe without acting (cheaper — no side effects)
info = await page.observe("Is there a login wall?")

await browser.close()
```

### Context manager support

```python
async with Browser() as browser:
    async with browser.open("https://example.com") as page:
        state = await page.snapshot()
        await page.click("Sign in")
```

---

## Core Data Structures

### PageSnapshot

```python
@dataclass
class PageSnapshot:
    version: int                    # increments on every snapshot; used for ref validation
    url: str
    title: str
    elements: list[Element]         # interactive elements only, semantically described
    text_content: str               # sanitized readable text, task-scoped
    tokens_estimated: int           # how many tokens this snapshot consumes
    changed_from_previous: bool     # differential flag
```

### Element

```python
@dataclass
class Element:
    ref: str                        # stable CDP node ID
    snapshot_version: int           # version when this ref was captured
    tag: str                        # semantic tag (button, input, link, etc.)
    role: str                       # ARIA role
    text: str                       # visible text
    placeholder: str | None         # for inputs
    interactive: bool
    in_shadow_dom: bool
```

### ActionResult

```python
@dataclass
class ActionResult:
    success: bool
    error: BrowserError | None
    page_changed: bool
    new_snapshot: PageSnapshot | None
    trace_entry: TraceEntry
```

### BrowserError

```python
class ErrorType(Enum):
    ELEMENT_STALE      = "element_stale"       # ref invalid after re-render
    ELEMENT_NOT_FOUND  = "element_not_found"   # semantic match failed
    ANTI_BOT_BLOCK     = "anti_bot_block"      # CAPTCHA or block detected
    AUTH_REQUIRED      = "auth_required"       # login wall encountered
    NETWORK_TIMEOUT    = "network_timeout"     # page or request timed out
    NAVIGATION_FAILED  = "navigation_failed"   # page did not load
    CANVAS_ELEMENT     = "canvas_element"      # element is in canvas (V2: vision fallback)

@dataclass
class BrowserError:
    type: ErrorType
    message: str
    confidence: float                          # 0.0–1.0
    recovery: list[RecoveryAction]             # ordered by recommendation

class RecoveryAction(Enum):
    RE_SNAPSHOT        = "re_snapshot"
    RETRY              = "retry"
    ROTATE_IDENTITY    = "rotate_identity"
    ESCALATE_TO_HUMAN  = "escalate_to_human"
    EXPONENTIAL_BACKOFF = "exponential_backoff"
    VISION_FALLBACK    = "vision_fallback"     # V2
```

### TraceEntry

```python
@dataclass
class TraceEntry:
    timestamp: float
    action: str                   # "click", "type", "snapshot", etc.
    input: dict                   # what was passed in
    output: dict                  # what came back
    tokens_consumed: int
    duration_ms: int
    error: BrowserError | None
```

---

## Layer Specifications

### Layer 4: CDP Engine

**Responsibility:** Launch Chrome, maintain WebSocket connection, execute raw CDP commands, traverse Shadow DOM.

**Browser launch:**
- Launch Chrome/Chromium with `--remote-debugging-port=0` (auto-assigned port)
- Read port from `DevToolsActivePort` file
- Connect via `websockets` library to the CDP endpoint

**Shadow DOM traversal:**
- Use `DOM.getFlattenedDocument` with `pierce=True` to traverse shadow roots
- Mark elements with `in_shadow_dom=True` in Element dataclass

**Extraction approach:**
- Pull only: node type, role, text content, placeholder, bounding box (for click targeting), and interactivity flag
- Never pull: raw HTML, scripts, styles, metadata — these are filtered at the CDP query level, not post-processed

**Page navigation:**
- Use `Page.navigate` CDP command
- Wait for `Page.loadEventFired` or `Page.domContentEventFired` (configurable)

### Layer 3: Error Recovery

**Responsibility:** Intercept all CDP errors and action failures, classify them into typed errors, attach recovery prescriptions.

**Element staleness detection:**
- Before every action, validate the element's `ref` against the current snapshot `version`
- If `element.snapshot_version != current_snapshot.version`, raise `ErrorType.ELEMENT_STALE` immediately — do not attempt the action

**Anti-bot detection:**
- Inspect page title and URL after navigation for known block patterns (e.g., "Access Denied", "Cloudflare", "captcha")
- Inspect response status codes via `Network.responseReceived` CDP event

### Layer 2: Security & Sanitization

**Responsibility:** Sanitize all page content before it is passed upward to Layer 1 or returned to the developer.

**Hidden element filtering:**
- Remove elements where computed style `display: none`, `visibility: hidden`, or `opacity: 0`
- Remove elements with `aria-hidden: true`
- Remove zero-size elements (width=0 or height=0)

**Prompt injection detection:**
- Pattern-match text content against known injection formats:
  - Instruction-format in non-content regions (nav, footer, metadata areas)
  - Text beginning with "Ignore previous", "System:", "Assistant:", etc.
- Flag detected patterns in the trace; strip from snapshot text before LLM exposure

**Context scoping:**
- When a task URL or region is specified, restrict text extraction to the main content region
- Heuristic: use `<main>`, `[role="main"]`, or largest content block as scope boundary

### Layer 1: Compression Engine

**Responsibility:** Transform sanitized CDP output into the most token-efficient representation possible while preserving all information the LLM needs to act.

**Semantic summary format (output to LLM):**

```
PAGE: Amazon.com — Search Results
URL: amazon.com/s?k=blue+sneakers
INTERACTIVE:
  [btn:1] "Add to Cart" — Nike Blue Sneaker $64.99
  [btn:2] "Add to Cart" — Adidas Runner Blue $59.00
  [inp:3] Search bar (current: "blue sneakers")
  [lnk:4] "Next page"
CONTENT:
  Showing 1–20 of 847 results for "blue sneakers"
  Filter: Price: Under $80 applied
```

This format is ~80 tokens. Raw HTML of the same page: ~12,000 tokens. Playwright accessibility tree: ~2,000 tokens.

**Element cache:**
- Cache element refs by semantic identity (tag + role + text hash)
- On re-snapshot, skip CDP re-query for cached elements unless `page_changed=True`
- Cache TTL: invalidated on every navigation or when CDP emits a DOM mutation event

**Snapshot versioning:**
- Increment `PageSnapshot.version` on every snapshot call
- All element refs carry the version they were captured in
- Layer 3 validates refs against current version before any action

**Differential updates:**
- Compare current snapshot to previous
- If `changed_from_previous=False`, return cached snapshot (0 CDP calls, 0 tokens)
- If changed, return only the diff (new/removed/modified elements) plus unchanged summary

---

## LLM Adapter Interface

`grip` is LLM-agnostic. Any object implementing this interface works with `run()`:

```python
class LLMAdapter(Protocol):
    async def complete(
        self,
        messages: list[dict],   # standard OpenAI-format messages
        tools: list[dict],      # grip's action tools as JSON schema
    ) -> LLMResponse: ...

@dataclass
class LLMResponse:
    content: str | None
    tool_call: ToolCall | None

@dataclass
class ToolCall:
    name: str          # "click", "type", "extract", "observe", "done"
    arguments: dict
```

Built-in adapters ship for OpenAI and Anthropic. Any other provider can be wrapped with 10 lines.

---

## Observability

Every layer emits structured events to a `Trace` object attached to the `Browser` session.

```python
trace = browser.trace          # access anytime
trace.actions                  # list[TraceEntry]
trace.total_tokens             # int
trace.total_duration_ms        # int
trace.errors                   # list[BrowserError]

# Export for fine-tuning or evaluation
trace.to_jsonl("session.jsonl")
```

Token count is tracked at every layer: snapshot tokens, extraction tokens, LLM tokens (when using `run()`).

---

## V1 Scope (Ships First)

| Component | Status |
|---|---|
| CDP Engine — Chrome launch, WebSocket connection, navigation | V1 |
| CDP Engine — Shadow DOM traversal (`pierce=True`) | V1 |
| Compression Engine — semantic summary format | V1 |
| Compression Engine — element cache + snapshot versioning | V1 |
| Compression Engine — differential updates | V1 |
| Security — hidden element filter | V1 |
| Security — prompt injection pattern detection | V1 |
| Error Recovery — all 6 typed error types | V1 |
| Error Recovery — element staleness pre-validation | V1 |
| Primitive API — `snapshot`, `click`, `type`, `extract`, `observe` | V1 |
| High-level API — `run(goal, llm)` | V1 |
| LLM adapters — OpenAI + Anthropic | V1 |
| Observability Trace — full action log + token counts | V1 |

## V2 Scope (After Validation)

| Component | Notes |
|---|---|
| Vision fallback for canvas apps | Trigger on `CANVAS_ELEMENT` error |
| Cloud browser backends (Browserbase, Steel) | Adapter pattern — same API |
| Advanced bot detection evasion | Behavioral timing, identity rotation |
| TypeScript SDK | Port core after Python validates |
| WebMCP support | When Chrome ships broadly |
| Production benchmark suite | Realistic network faults, bot detection |

---

## Project Structure

```
agentbrowser/
├── grip/
│   ├── __init__.py              # public API exports
│   ├── browser.py               # Browser class, session management
│   ├── page.py                  # Page class, primitive API
│   ├── runner.py                # run() high-level loop
│   ├── cdp/
│   │   ├── engine.py            # CDP WebSocket client
│   │   ├── launcher.py          # Chrome process launch
│   │   └── shadow.py            # Shadow DOM traversal
│   ├── compression/
│   │   ├── summarizer.py        # DOM → semantic summary
│   │   ├── cache.py             # element cache
│   │   └── diff.py              # differential updates
│   ├── security/
│   │   ├── sanitizer.py         # hidden element filter
│   │   └── injection.py         # prompt injection detection
│   ├── errors/
│   │   ├── types.py             # ErrorType, BrowserError, RecoveryAction
│   │   └── classifier.py        # error classification logic
│   ├── trace.py                 # Trace, TraceEntry
│   └── adapters/
│       ├── openai.py            # OpenAI LLM adapter
│       └── anthropic.py         # Anthropic LLM adapter
├── tests/
│   ├── unit/
│   └── integration/
├── docs/
│   └── superpowers/specs/
│       └── 2026-05-17-grip-design.md
├── pyproject.toml
└── README.md
```

---

## Key Design Constraints (Non-Negotiable)

1. **Token count is always tracked.** Every snapshot, extraction, and LLM call records tokens consumed. Developers can always see the cost of each operation.
2. **The LLM never sees raw HTML.** Only the compressed semantic summary passes through Layer 1.
3. **Element refs are validated before every action.** Stale refs raise a typed error — they never cause silent failures.
4. **All page content is sanitized before the LLM sees it.** Hidden elements and injection patterns are stripped in Layer 2.
5. **Errors are always typed.** No operation returns a bare string error. Every failure is a `BrowserError` with type, confidence, and recovery actions.
