"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { cn } from "@/lib/utils";
import { CopyButton } from "@/components/copy-button";
import { Eyebrow, Lede, SectionHeading } from "@/components/section";
import { Reveal } from "@/components/reveal";

// Every call here exists on grip.Page — the snippets are lifted from the README
// rather than written for the page, so they cannot drift into an API that does
// not ship.
const TABS = [
  {
    id: "snapshot",
    label: "Snapshot",
    filename: "quick_start.py",
    code: `import asyncio
from grip import Browser

async def main():
    async with Browser(headless=True) as browser:
        page = await browser.open("https://news.ycombinator.com")
        snapshot = await page.snapshot()

        print(snapshot.text_content)      # readable page text
        print(snapshot.elements)          # interactive elements only
        print(snapshot.tokens_estimated)  # what this turn will cost

asyncio.run(main())`,
  },
  {
    id: "loop",
    label: "Agent loop",
    filename: "agent_loop.py",
    code: `async with Browser(headless=True) as browser:
    page = await browser.open("https://amazon.com")
    await page.snapshot()               # build element index

    await page.type("search", "blue sneakers")
    await page.click("Go")              # fuzzy match, no selectors needed

    await page.snapshot()               # re-index after navigation
    doc = await page.read()             # prose, citable blocks, no nav chrome

    shot = await page.screenshot()      # JPEG, for vision models
    shot.save("result.jpg")`,
  },
  {
    id: "errors",
    label: "Typed errors",
    filename: "recover.py",
    code: `from grip import GripError
from grip.errors.types import ErrorType

try:
    await page.click("checkout")
except GripError as e:
    match e.error.type:
        case ErrorType.ELEMENT_STALE:      # element moved after navigation
            await page.snapshot()
            await page.click("checkout")
        case ErrorType.RATE_LIMITED:       # 429: back off, then retry
            await asyncio.sleep(30)
        case ErrorType.CAPTCHA_REQUIRED:   # escalate; grip will not guess
            await escalate(e.error.message)`,
  },
  {
    id: "autonomous",
    label: "Autonomous",
    filename: "autonomous.py",
    code: `from grip import Browser
from grip.adapters.anthropic import AnthropicAdapter

llm = AnthropicAdapter(api_key="sk-ant-...")

async with Browser(llm=llm, headless=True) as browser:
    result = await browser.run(
        goal="Find the cheapest blue sneakers under $80",
        url="https://amazon.com",
    )
    print(result.data)
    print(f"Used {result.tokens} tokens")`,
  },
] as const;

const KEYWORDS = new Set([
  "import",
  "from",
  "async",
  "await",
  "def",
  "with",
  "as",
  "try",
  "except",
  "match",
  "case",
  "return",
  "print",
]);

/** Deliberately small: split on comment, then string, then bare words. A full
 * highlighter would be more weight than four snippets are worth. */
function highlight(line: string, key: number) {
  const commentAt = findCommentStart(line);
  const code = commentAt === -1 ? line : line.slice(0, commentAt);
  const comment = commentAt === -1 ? null : line.slice(commentAt);

  const parts = code.split(/("[^"]*")/g);

  return (
    <div key={key}>
      {parts.map((part, i) =>
        part.startsWith('"') && part.endsWith('"') && part.length > 1 ? (
          <span key={i} className="text-[var(--primary)]">
            {part}
          </span>
        ) : (
          <span key={i}>
            {part.split(/(\b)/).map((word, j) =>
              KEYWORDS.has(word) ? (
                <span key={j} className="font-medium text-foreground">
                  {word}
                </span>
              ) : (
                <span key={j} className="text-foreground/70">
                  {word}
                </span>
              ),
            )}
          </span>
        ),
      )}
      {comment && <span className="text-muted-foreground">{comment}</span>}
      {line === "" && " "}
    </div>
  );
}

/** `#` inside a string literal is not a comment. */
function findCommentStart(line: string) {
  let inString = false;
  for (let i = 0; i < line.length; i += 1) {
    if (line[i] === '"') inString = !inString;
    if (line[i] === "#" && !inString) return i;
  }
  return -1;
}

export function CodeShowcase() {
  const [active, setActive] = useState<string>(TABS[0].id);
  const current = TABS.find((t) => t.id === active) ?? TABS[0];

  return (
    <section id="code" className="px-6 py-24 sm:py-32">
      <div className="mx-auto max-w-5xl">
        <Reveal>
          <Eyebrow index="04">The API</Eyebrow>
          <SectionHeading>Describe the element. Not the selector.</SectionHeading>
          <Lede>
            grip resolves &ldquo;Go&rdquo; or &ldquo;search&rdquo; against the
            indexed snapshot, traverses shadow DOM without special-casing, and
            raises typed errors your loop can branch on instead of strings it has
            to parse.
          </Lede>
        </Reveal>

        <Reveal delay={0.08}>
          <div className="mt-12 overflow-hidden rounded-[12px] border border-border bg-card">
            <div className="flex items-center gap-1 overflow-x-auto border-b border-border px-2">
              {TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActive(tab.id)}
                  aria-current={active === tab.id}
                  className={cn(
                    "relative shrink-0 px-3 py-3 text-[12px] whitespace-nowrap transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                    active === tab.id
                      ? "text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {tab.label}
                  {active === tab.id && (
                    <motion.span
                      layoutId="code-tab"
                      className="absolute inset-x-2 -bottom-px h-px bg-[var(--primary)]"
                      transition={{ type: "spring", stiffness: 480, damping: 40 }}
                    />
                  )}
                </button>
              ))}
              <div className="ml-auto flex shrink-0 items-center gap-2 pr-1 pl-4">
                <span className="hidden font-mono text-[11px] text-muted-foreground sm:inline">
                  {current.filename}
                </span>
                <CopyButton value={current.code} label="Copy snippet" />
              </div>
            </div>

            <AnimatePresence mode="wait">
              <motion.pre
                key={active}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.18 }}
                className="min-h-[300px] overflow-x-auto p-5 font-mono text-[12.5px] leading-[1.75] sm:p-6"
              >
                <code>{current.code.split("\n").map(highlight)}</code>
              </motion.pre>
            </AnimatePresence>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
