"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";

const TABS = [
  {
    id: "quickstart",
    label: "Quick start",
    filename: "quick_start.py",
    code: `import asyncio
from grip import Browser

async def main():
    async with Browser(headless=True) as browser:
        page = await browser.open("https://news.ycombinator.com")
        snapshot = await page.snapshot()

        print(snapshot.text_content)       # readable page text
        print(snapshot.elements)           # interactive elements only
        print(snapshot.tokens_estimated)   # ~50

asyncio.run(main())`,
  },
  {
    id: "agentloop",
    label: "Agent loop",
    filename: "agent_loop.py",
    code: `async with Browser(headless=True) as browser:
    page = await browser.open("https://amazon.com")
    await page.snapshot()                # build element index

    await page.type("search", "blue sneakers")
    await page.click("Go")               # fuzzy match — no selectors

    await page.snapshot()                # re-index after navigation
    data = await page.extract({
        "product": "str",
        "price": "str"
    })

    shot = await page.screenshot()       # JPEG, ~800 tokens
    shot.save("result.jpg")`,
  },
  {
    id: "autonomous",
    label: "Autonomous mode",
    filename: "autonomous.py",
    code: `from grip import Browser
from grip.adapters.anthropic import AnthropicAdapter

llm = AnthropicAdapter(api_key="sk-ant-...")

async with Browser(llm=llm, headless=True) as browser:
    result = await browser.run(
        goal="Find the cheapest blue sneakers under $80",
        url="https://amazon.com"
    )
    print(result.data)
    print(f"Used {result.tokens} tokens")`,
  },
];

export function CodeShowcase() {
  const [active, setActive] = useState(TABS[0].id);
  const current = TABS.find((t) => t.id === active)!;

  return (
    <section className="px-6 py-24 max-w-4xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-60px" }}
        transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] }}
        className="text-center mb-12"
      >
        <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight text-white">
          Three lines to a working agent
        </h2>
        <p className="mt-3 text-white/40 max-w-md mx-auto text-sm">
          From a single snapshot to a fully autonomous browsing loop.
        </p>
      </motion.div>

      <div className="rounded-2xl border border-white/[0.08] bg-[#111113] overflow-hidden">
        {/* Tab bar */}
        <div className="flex items-center gap-1 px-4 pt-3 pb-0 border-b border-white/[0.06]">
          <span className="w-2.5 h-2.5 rounded-full bg-white/10 mr-1" />
          <span className="w-2.5 h-2.5 rounded-full bg-white/10 mr-4" />
          <span className="w-2.5 h-2.5 rounded-full bg-white/10 mr-4" />

          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActive(tab.id)}
              className={cn(
                "px-3 py-2 text-[11px] font-mono transition-colors duration-150 border-b-2 -mb-px",
                active === tab.id
                  ? "text-white border-white/40"
                  : "text-white/30 border-transparent hover:text-white/60"
              )}
            >
              {tab.label}
            </button>
          ))}

          <span className="ml-auto text-[10px] text-white/20 font-mono pb-2">
            {current.filename}
          </span>
        </div>

        {/* Code */}
        <AnimatePresence mode="wait">
          <motion.pre
            key={active}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="p-6 text-[12px] sm:text-[13px] font-mono text-white/70 overflow-x-auto leading-relaxed min-h-[220px]"
          >
            <code>{current.code}</code>
          </motion.pre>
        </AnimatePresence>
      </div>
    </section>
  );
}
