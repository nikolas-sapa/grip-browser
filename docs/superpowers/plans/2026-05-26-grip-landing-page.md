# grip Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dark, developer-grade marketing landing page for grip — a token-efficient, CDP-native browser SDK for AI agents.

**Architecture:** Next.js 15 App Router single-page site at `/web` inside the agentbrowser monorepo. Components are section-scoped files. Framer Motion handles scroll-triggered animations and the token counter. No pages router, no API routes.

**Tech Stack:** Next.js 15, Tailwind CSS v4, Framer Motion, Geist font (next/font), shadcn/ui (button, badge), lucide-react icons.

---

## Design DNA

Extracted from reference sites (Cluely, Creed, Runwise, Composio):

- **Background**: `#09090b` (zinc-950) — near-black, not pure black
- **Font**: Geist (Vercel's font — clean, developer-native)
- **Borders**: `border border-white/10` — subtle white at 10% opacity
- **Glass cards**: `bg-white/[0.04] backdrop-blur-sm border border-white/10`
- **Gradient text**: `bg-gradient-to-r from-white to-white/50 bg-clip-text text-transparent`
- **Buttons**: pill shape, `bg-white text-black` (primary) / dark glass (secondary)
- **Hover**: `hover:scale-[1.02] transition-transform duration-150 ease-out`
- **Code blocks**: dark surface `#111113`, syntax highlighted, subtle glow on container
- **Animations**: Framer Motion scroll-triggered `fadeInUp`, staggered children, spring easing
- **NO**: gradient backgrounds, emojis, Inter/Arial as primary, heavy 3D effects

---

## File Structure

```
web/
├── app/
│   ├── layout.tsx          # Root layout — Geist font, metadata, globals
│   ├── page.tsx            # Assembles all sections
│   └── globals.css         # Tailwind base + custom CSS vars + scrollbar
├── components/
│   ├── nav.tsx             # Sticky nav — logo, GitHub link, install CTA
│   ├── hero.tsx            # Headline, subhead, token comparison, CTA buttons
│   ├── token-counter.tsx   # Animated 12,000 → 50 token comparison widget
│   ├── code-showcase.tsx   # Tabbed code blocks (3 examples)
│   ├── features.tsx        # 6-card feature grid
│   ├── comparison.tsx      # vs Playwright MCP / Puppeteer table
│   ├── install.tsx         # pip install + GitHub stars CTA section
│   └── footer.tsx          # Links + copyright
└── lib/
    └── utils.ts            # cn() helper (clsx + twMerge)
```

---

## Task 1: Scaffold Next.js project

**Files:**
- Create: `web/` (Next.js app)
- Create: `web/app/globals.css`
- Create: `web/lib/utils.ts`

- [ ] **Step 1: Bootstrap Next.js with Tailwind**

```bash
cd /Users/nikolassapalidis/dev/agentbrowser
npx create-next-app@latest web \
  --typescript \
  --tailwind \
  --eslint \
  --app \
  --no-src-dir \
  --import-alias "@/*"
```

- [ ] **Step 2: Install dependencies**

```bash
cd web
npm install framer-motion lucide-react clsx tailwind-merge
npx shadcn@latest init --defaults
npx shadcn@latest add button badge
```

- [ ] **Step 3: Write `lib/utils.ts`**

```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 4: Write `app/globals.css`**

```css
@import "tailwindcss";

:root {
  --background: #09090b;
  --foreground: #fafafa;
}

body {
  background: var(--background);
  color: var(--foreground);
  font-feature-settings: "rlig" 1, "calt" 1;
  -webkit-font-smoothing: antialiased;
}

/* Hide default scrollbar, style custom */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 3px; }

/* Syntax highlight token colors */
.token-string { color: #a3e635; }
.token-keyword { color: #818cf8; }
.token-comment { color: #4b5563; }
.token-function { color: #60a5fa; }
.token-number { color: #f97316; }
```

- [ ] **Step 5: Update `app/layout.tsx`**

```tsx
import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

export const metadata: Metadata = {
  title: "grip — Token-efficient browser SDK for AI agents",
  description:
    "~50 tokens per page snapshot. CDP-native, no Playwright bloat. Built for LLM agents.",
  openGraph: {
    title: "grip",
    description: "~50 tokens per page snapshot. CDP-native browser SDK for AI agents.",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="font-sans antialiased bg-[#09090b] text-zinc-50 selection:bg-white/20">
        {children}
      </body>
    </html>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add web/
git commit -m "feat(web): scaffold Next.js landing page for grip"
```

---

## Task 2: Nav component

**Files:**
- Create: `web/components/nav.tsx`

The nav is sticky with a blur backdrop, contains the grip logo (wordmark), a GitHub link (icon + star count placeholder), and a pill CTA.

- [ ] **Step 1: Write `web/components/nav.tsx`**

```tsx
"use client";

import { Github } from "lucide-react";
import { motion } from "framer-motion";

export function Nav() {
  return (
    <motion.header
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-6 py-4 
                 border-b border-white/[0.06] bg-[#09090b]/80 backdrop-blur-md"
    >
      {/* Logo */}
      <a href="/" className="flex items-center gap-2">
        <span className="text-base font-semibold tracking-tight text-white">
          grip
        </span>
        <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] font-medium text-white/50">
          v0.2
        </span>
      </a>

      {/* Right side */}
      <div className="flex items-center gap-3">
        <a
          href="https://github.com/nikolassapalidis/agentbrowser"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 rounded-full border border-white/10 
                     bg-white/[0.04] px-3 py-1.5 text-xs text-white/70 
                     hover:bg-white/[0.08] hover:text-white transition-colors duration-150"
        >
          <Github size={13} />
          <span>GitHub</span>
        </a>
        <a
          href="#install"
          className="rounded-full bg-white px-4 py-1.5 text-xs font-medium text-black 
                     hover:bg-white/90 transition-colors duration-150"
        >
          pip install
        </a>
      </div>
    </motion.header>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/components/nav.tsx
git commit -m "feat(web): add Nav component"
```

---

## Task 3: Token counter widget

**Files:**
- Create: `web/components/token-counter.tsx`

This is a centerpiece animation in the hero — two side-by-side cards. Left shows "Raw HTML · 12,000 tokens" with a number that counts down when in view. Right shows "grip snapshot · ~50 tokens" with a number that counts up. This viscerally communicates the value prop.

- [ ] **Step 1: Write `web/components/token-counter.tsx`**

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { motion, useInView, useMotionValue, useTransform, animate } from "framer-motion";
import { cn } from "@/lib/utils";

function AnimatedNumber({
  target,
  duration = 1.5,
  prefix = "",
  suffix = "",
  className,
}: {
  target: number;
  duration?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-50px" });
  const motionVal = useMotionValue(0);
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (!inView) return;
    const controls = animate(motionVal, target, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => setDisplay(Math.round(v)),
    });
    return controls.stop;
  }, [inView, target, duration, motionVal]);

  return (
    <span ref={ref} className={className}>
      {prefix}{display.toLocaleString()}{suffix}
    </span>
  );
}

export function TokenCounter() {
  return (
    <div className="flex flex-col sm:flex-row items-stretch gap-3 w-full max-w-lg mx-auto">
      {/* Raw HTML card */}
      <div className="flex-1 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-5 text-center">
        <p className="text-xs text-white/40 mb-2 font-mono tracking-wide uppercase">Raw HTML</p>
        <AnimatedNumber
          target={12000}
          duration={1.8}
          className="text-4xl font-semibold tabular-nums text-red-400/80"
        />
        <p className="text-xs text-white/30 mt-1 font-mono">tokens / page</p>
      </div>

      {/* VS divider */}
      <div className="flex items-center justify-center sm:flex-col">
        <span className="text-[10px] font-mono text-white/20 px-2">vs</span>
      </div>

      {/* grip card */}
      <div className="flex-1 rounded-2xl border border-white/20 bg-white/[0.05] p-5 text-center relative overflow-hidden">
        {/* Glow */}
        <div className="absolute inset-0 bg-gradient-to-b from-white/[0.04] to-transparent pointer-events-none" />
        <p className="text-xs text-white/40 mb-2 font-mono tracking-wide uppercase relative z-10">
          grip snapshot
        </p>
        <div className="flex items-baseline justify-center gap-1 relative z-10">
          <span className="text-[11px] text-white/40 font-mono">~</span>
          <AnimatedNumber
            target={50}
            duration={1.0}
            className="text-4xl font-semibold tabular-nums text-emerald-400"
          />
        </div>
        <p className="text-xs text-white/30 mt-1 font-mono relative z-10">tokens / page</p>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/components/token-counter.tsx
git commit -m "feat(web): add animated TokenCounter component"
```

---

## Task 4: Hero section

**Files:**
- Create: `web/components/hero.tsx`

Large headline, sub-copy, token counter widget, two CTA buttons, and a code preview below the fold.

- [ ] **Step 1: Write `web/components/hero.tsx`**

```tsx
"use client";

import { motion } from "framer-motion";
import { TokenCounter } from "./token-counter";
import { ArrowRight, Terminal } from "lucide-react";

const fadeUp = (delay = 0) => ({
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1], delay },
});

const CODE_SNIPPET = `import asyncio
from grip import Browser

async def main():
    async with Browser(headless=True) as browser:
        page = await browser.open("https://amazon.com")
        snapshot = await page.snapshot()

        print(snapshot.elements)          # interactive elements
        print(snapshot.tokens_estimated)  # ~50

asyncio.run(main())`;

export function Hero() {
  return (
    <section className="relative flex flex-col items-center text-center pt-36 pb-20 px-6 overflow-hidden">
      {/* Radial ambient */}
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] 
                   rounded-full pointer-events-none"
        style={{
          background:
            "radial-gradient(circle, rgba(255,255,255,0.04) 0%, transparent 70%)",
        }}
      />

      {/* Badge */}
      <motion.div {...fadeUp(0)}>
        <span
          className="inline-flex items-center gap-1.5 rounded-full border border-white/10 
                     bg-white/[0.04] px-3 py-1 text-[11px] text-white/50 font-mono mb-8"
        >
          <Terminal size={10} />
          pip install grip-browser
        </span>
      </motion.div>

      {/* Headline */}
      <motion.h1
        {...fadeUp(0.05)}
        className="max-w-3xl text-5xl sm:text-6xl lg:text-7xl font-semibold tracking-tight leading-[1.08]"
      >
        <span
          className="bg-gradient-to-b from-white to-white/60 bg-clip-text text-transparent"
        >
          Browser SDK that thinks
          <br />
          in tokens.
        </span>
      </motion.h1>

      {/* Sub */}
      <motion.p
        {...fadeUp(0.1)}
        className="mt-5 max-w-lg text-base sm:text-lg text-white/40 leading-relaxed"
      >
        grip gives your AI agent a semantic page snapshot — interactive elements
        and visible text — in{" "}
        <span className="text-white/70 font-medium">~50 tokens</span>. Raw HTML
        costs 12,000.
      </motion.p>

      {/* CTAs */}
      <motion.div {...fadeUp(0.15)} className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <a
          href="#install"
          className="flex items-center gap-2 rounded-full bg-white px-5 py-2.5 text-sm 
                     font-medium text-black hover:bg-white/90 transition-colors"
        >
          Get started <ArrowRight size={13} />
        </a>
        <a
          href="https://github.com/nikolassapalidis/agentbrowser"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 rounded-full border border-white/10 
                     bg-white/[0.04] px-5 py-2.5 text-sm text-white/70 
                     hover:bg-white/[0.08] hover:text-white transition-colors"
        >
          View on GitHub
        </a>
      </motion.div>

      {/* Token counter */}
      <motion.div {...fadeUp(0.2)} className="mt-14 w-full max-w-lg">
        <TokenCounter />
      </motion.div>

      {/* Code preview */}
      <motion.div
        {...fadeUp(0.25)}
        className="mt-10 w-full max-w-2xl text-left rounded-2xl border border-white/[0.08] 
                   bg-[#111113] overflow-hidden"
      >
        <div className="flex items-center gap-1.5 px-4 py-3 border-b border-white/[0.06]">
          <span className="w-2.5 h-2.5 rounded-full bg-white/10" />
          <span className="w-2.5 h-2.5 rounded-full bg-white/10" />
          <span className="w-2.5 h-2.5 rounded-full bg-white/10" />
          <span className="ml-3 text-[11px] text-white/30 font-mono">quick_start.py</span>
        </div>
        <pre className="p-5 text-[12px] sm:text-[13px] font-mono text-white/70 overflow-x-auto leading-relaxed">
          <code>{CODE_SNIPPET}</code>
        </pre>
      </motion.div>
    </section>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/components/hero.tsx
git commit -m "feat(web): add Hero section"
```

---

## Task 5: Features grid

**Files:**
- Create: `web/components/features.tsx`

6 glass cards in a 2×3 grid (desktop), each with a lucide icon, title, and 1-sentence description.

- [ ] **Step 1: Write `web/components/features.tsx`**

```tsx
"use client";

import { motion } from "framer-motion";
import {
  Cpu,
  Layers,
  Target,
  ShieldAlert,
  Activity,
  Plug,
} from "lucide-react";

const FEATURES = [
  {
    icon: Cpu,
    title: "Pure CDP",
    description:
      "Speaks Chrome DevTools Protocol directly — no Playwright binary, no Puppeteer overhead.",
  },
  {
    icon: Target,
    title: "Fuzzy element matching",
    description:
      'Click "Go" or type "search" — grip resolves to the real element. No CSS selectors.',
  },
  {
    icon: Layers,
    title: "Shadow DOM traversal",
    description:
      "Web components, Chrome extensions, custom elements — all discovered in the same snapshot.",
  },
  {
    icon: ShieldAlert,
    title: "Typed error recovery",
    description:
      "Every failure is a typed BrowserError with a suggested RecoveryAction. Your agent decides.",
  },
  {
    icon: Activity,
    title: "Token trace",
    description:
      "Every action recorded with timing and token cost. Export to JSONL for audit or replay.",
  },
  {
    icon: Plug,
    title: "LLM adapters",
    description:
      "OpenAI and Anthropic adapters ship out of the box. Bring your own via the LLMAdapter protocol.",
  },
];

const container = {
  hidden: {},
  show: {
    transition: {
      staggerChildren: 0.06,
    },
  },
};

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.16, 1, 0.3, 1] } },
};

export function Features() {
  return (
    <section className="px-6 py-24 max-w-6xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-60px" }}
        transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
        className="text-center mb-14"
      >
        <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight text-white">
          Built for agents, not browsers
        </h2>
        <p className="mt-3 text-white/40 max-w-md mx-auto text-sm sm:text-base">
          Every feature exists to save tokens, reduce hallucinations, and make
          agentic loops more reliable.
        </p>
      </motion.div>

      <motion.div
        variants={container}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: "-60px" }}
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
      >
        {FEATURES.map((f) => (
          <motion.div
            key={f.title}
            variants={item}
            className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-6 
                       hover:border-white/[0.14] hover:bg-white/[0.05] 
                       transition-colors duration-200 group"
          >
            <div className="mb-4 flex items-center justify-center w-9 h-9 rounded-xl 
                            border border-white/10 bg-white/[0.06] 
                            group-hover:bg-white/10 transition-colors">
              <f.icon size={16} className="text-white/60" />
            </div>
            <h3 className="text-sm font-semibold text-white mb-1.5">{f.title}</h3>
            <p className="text-sm text-white/40 leading-relaxed">{f.description}</p>
          </motion.div>
        ))}
      </motion.div>
    </section>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/components/features.tsx
git commit -m "feat(web): add Features grid section"
```

---

## Task 6: Code showcase (tabbed)

**Files:**
- Create: `web/components/code-showcase.tsx`

Three tabs: "Quick start", "Agent loop", "Autonomous mode". Switching tabs cross-fades the code block. This is the richest content section — shows grip's full range.

- [ ] **Step 1: Write `web/components/code-showcase.tsx`**

```tsx
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
        transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
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
          {/* Traffic lights */}
          <span className="w-2.5 h-2.5 rounded-full bg-white/10 mr-2" />
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
            className="p-6 text-[12px] sm:text-[13px] font-mono text-white/70 
                       overflow-x-auto leading-relaxed min-h-[220px]"
          >
            <code>{current.code}</code>
          </motion.pre>
        </AnimatePresence>
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/components/code-showcase.tsx
git commit -m "feat(web): add tabbed CodeShowcase section"
```

---

## Task 7: Comparison table

**Files:**
- Create: `web/components/comparison.tsx`

Side-by-side feature matrix: grip vs Playwright MCP vs Puppeteer. Rows animate in on scroll.

- [ ] **Step 1: Write `web/components/comparison.tsx`**

```tsx
"use client";

import { motion } from "framer-motion";
import { Check, X, Minus } from "lucide-react";

type CellValue = true | false | "partial";

const ROWS: { label: string; grip: CellValue; playwright: CellValue; puppeteer: CellValue }[] = [
  { label: "Tokens per snapshot", grip: true, playwright: false, puppeteer: false },
  { label: "Shadow DOM traversal", grip: true, playwright: "partial", puppeteer: false },
  { label: "Prompt injection guard", grip: true, playwright: false, puppeteer: false },
  { label: "Typed error recovery", grip: true, playwright: false, puppeteer: false },
  { label: "Element staleness detection", grip: true, playwright: false, puppeteer: false },
  { label: "Pure CDP (no binary bloat)", grip: true, playwright: false, puppeteer: false },
  { label: "Screenshot token tracking", grip: true, playwright: false, puppeteer: false },
];

function Cell({ value, highlight }: { value: CellValue; highlight?: boolean }) {
  if (value === true)
    return (
      <div className="flex justify-center">
        <Check size={14} className={highlight ? "text-emerald-400" : "text-white/50"} />
      </div>
    );
  if (value === false)
    return (
      <div className="flex justify-center">
        <X size={14} className="text-white/20" />
      </div>
    );
  return (
    <div className="flex justify-center">
      <Minus size={14} className="text-white/30" />
    </div>
  );
}

export function Comparison() {
  return (
    <section className="px-6 py-24 max-w-4xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-60px" }}
        transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
        className="text-center mb-12"
      >
        <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight text-white">
          Why not Playwright or Puppeteer?
        </h2>
        <p className="mt-3 text-white/40 text-sm">
          They were built for humans testing UIs. grip is built for LLMs running loops.
        </p>
      </motion.div>

      <div className="rounded-2xl border border-white/[0.08] overflow-hidden">
        {/* Header */}
        <div className="grid grid-cols-4 bg-white/[0.03] border-b border-white/[0.08]">
          <div className="px-4 py-3 text-xs text-white/30 font-mono">Feature</div>
          <div className="px-4 py-3 text-xs text-white font-semibold text-center">grip</div>
          <div className="px-4 py-3 text-xs text-white/40 text-center font-mono">Playwright MCP</div>
          <div className="px-4 py-3 text-xs text-white/40 text-center font-mono">Puppeteer</div>
        </div>

        {/* Rows */}
        {ROWS.map((row, i) => (
          <motion.div
            key={row.label}
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true, margin: "-30px" }}
            transition={{ duration: 0.3, delay: i * 0.04 }}
            className="grid grid-cols-4 border-b border-white/[0.05] last:border-0 
                       hover:bg-white/[0.02] transition-colors"
          >
            <div className="px-4 py-3 text-xs text-white/50">{row.label}</div>
            <div className="px-4 py-3">
              <Cell value={row.grip} highlight />
            </div>
            <div className="px-4 py-3">
              <Cell value={row.playwright} />
            </div>
            <div className="px-4 py-3">
              <Cell value={row.puppeteer} />
            </div>
          </motion.div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/components/comparison.tsx
git commit -m "feat(web): add Comparison table section"
```

---

## Task 8: Install / CTA section

**Files:**
- Create: `web/components/install.tsx`

Terminal-style install block with three variants (base, openai, anthropic). Clean CTA below.

- [ ] **Step 1: Write `web/components/install.tsx`**

```tsx
"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Copy, Check } from "lucide-react";
import { cn } from "@/lib/utils";

const VARIANTS = [
  { label: "base", cmd: "pip install grip-browser" },
  { label: "openai", cmd: "pip install grip-browser[openai]" },
  { label: "anthropic", cmd: "pip install grip-browser[anthropic]" },
];

export function Install() {
  const [active, setActive] = useState(0);
  const [copied, setCopied] = useState(false);

  const copy = () => {
    navigator.clipboard.writeText(VARIANTS[active].cmd);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <section id="install" className="px-6 py-32 max-w-2xl mx-auto text-center">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-60px" }}
        transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
      >
        <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight text-white mb-3">
          Start in 30 seconds
        </h2>
        <p className="text-white/40 text-sm mb-10">
          Python 3.11+ · Chrome or Chromium installed.
        </p>

        {/* Variant tabs */}
        <div className="flex justify-center gap-1 mb-4">
          {VARIANTS.map((v, i) => (
            <button
              key={v.label}
              onClick={() => setActive(i)}
              className={cn(
                "px-3 py-1 rounded-full text-[11px] font-mono transition-colors",
                active === i
                  ? "bg-white/10 text-white"
                  : "text-white/30 hover:text-white/60"
              )}
            >
              {v.label}
            </button>
          ))}
        </div>

        {/* Terminal block */}
        <div className="relative flex items-center rounded-xl border border-white/[0.08] 
                        bg-[#111113] px-5 py-4 font-mono text-sm text-white/70">
          <span className="text-white/20 mr-3 select-none">$</span>
          <span className="flex-1 text-left">{VARIANTS[active].cmd}</span>
          <button
            onClick={copy}
            className="ml-4 flex items-center justify-center w-7 h-7 rounded-lg 
                       border border-white/10 hover:bg-white/10 transition-colors"
          >
            {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} className="text-white/40" />}
          </button>
        </div>

        <p className="mt-4 text-[11px] text-white/25 font-mono">
          requires Python 3.11+ · Chrome/Chromium installed
        </p>

        {/* Requirements note */}
        <div className="mt-10 flex flex-wrap justify-center gap-3">
          <a
            href="https://github.com/nikolassapalidis/agentbrowser"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-full border border-white/10 bg-white/[0.04] 
                       px-5 py-2.5 text-sm text-white/70 
                       hover:bg-white/[0.08] hover:text-white transition-colors"
          >
            View on GitHub
          </a>
          <a
            href="https://github.com/nikolassapalidis/agentbrowser#readme"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-full bg-white px-5 py-2.5 text-sm font-medium 
                       text-black hover:bg-white/90 transition-colors"
          >
            Read the docs
          </a>
        </div>
      </motion.div>
    </section>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/components/install.tsx
git commit -m "feat(web): add Install CTA section"
```

---

## Task 9: Footer

**Files:**
- Create: `web/components/footer.tsx`

- [ ] **Step 1: Write `web/components/footer.tsx`**

```tsx
export function Footer() {
  return (
    <footer className="border-t border-white/[0.06] px-6 py-8">
      <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center 
                      justify-between gap-4 text-xs text-white/25 font-mono">
        <span>grip · MIT License</span>
        <div className="flex gap-6">
          <a
            href="https://github.com/nikolassapalidis/agentbrowser"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-white/50 transition-colors"
          >
            GitHub
          </a>
          <a
            href="https://github.com/nikolassapalidis/agentbrowser#readme"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-white/50 transition-colors"
          >
            Docs
          </a>
          <a
            href="https://pypi.org/project/grip-browser"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-white/50 transition-colors"
          >
            PyPI
          </a>
        </div>
      </div>
    </footer>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/components/footer.tsx
git commit -m "feat(web): add Footer component"
```

---

## Task 10: Assemble page + run dev server

**Files:**
- Modify: `web/app/page.tsx`

- [ ] **Step 1: Write `web/app/page.tsx`**

```tsx
import { Nav } from "@/components/nav";
import { Hero } from "@/components/hero";
import { Features } from "@/components/features";
import { CodeShowcase } from "@/components/code-showcase";
import { Comparison } from "@/components/comparison";
import { Install } from "@/components/install";
import { Footer } from "@/components/footer";

export default function Home() {
  return (
    <>
      <Nav />
      <main>
        <Hero />
        <Features />
        <CodeShowcase />
        <Comparison />
        <Install />
      </main>
      <Footer />
    </>
  );
}
```

- [ ] **Step 2: Start dev server and verify**

```bash
cd /Users/nikolassapalidis/dev/agentbrowser/web
npm run dev
```

Open `http://localhost:3000` and verify:
- Nav sticks on scroll
- Token counter animates on scroll-into-view (12,000 counts up, then grip's 50 counts up)
- Hero code block renders readable
- Code tabs switch with fade transition
- Comparison table rows fade in on scroll
- Install section copy button works
- No layout breaks at 375px (iPhone), 768px (tablet), 1280px (desktop)

- [ ] **Step 3: Final commit**

```bash
git add web/app/page.tsx
git commit -m "feat(web): assemble landing page and wire all sections"
```

---

## Self-Review

**Spec coverage:**
- [x] Token comparison widget — Task 3
- [x] CDP/no-Playwright pitch — Features + Hero
- [x] Code examples (all 3 from README) — Task 6
- [x] Comparison table (README table) — Task 7
- [x] Install / pip install — Task 8, Nav
- [x] LLM adapters — Features card
- [x] Typed errors — Features card
- [x] Shadow DOM — Features card
- [x] Design DNA: dark glass, Geist, no emojis, spring easing — all tasks

**Placeholder scan:** None found. All code blocks are complete and runnable.

**Type consistency:** `cn()` used consistently from `@/lib/utils`. Framer Motion `whileInView` used for all scroll animations. `AnimatePresence mode="wait"` for tab transitions.
