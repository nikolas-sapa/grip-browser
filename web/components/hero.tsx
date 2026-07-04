"use client";

import { motion } from "framer-motion";
import { HeroVisual } from "./hero-visual";
import { ArrowRight, Terminal } from "lucide-react";

const fadeUp = (delay = 0) => ({
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] as [number, number, number, number], delay },
});


export function Hero() {
  return (
    <section className="relative flex flex-col items-center text-center pt-36 pb-20 px-6 overflow-hidden">
      {/* Badge */}
      <motion.div {...fadeUp(0)}>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[11px] text-white/50 font-mono mb-8">
          <Terminal size={10} />
          pip install grip-browser
        </span>
      </motion.div>

      {/* Headline */}
      <motion.h1
        {...fadeUp(0.05)}
        className="max-w-3xl text-5xl sm:text-6xl lg:text-7xl font-semibold tracking-tight leading-[1.08]"
      >
        <span className="text-white">
          50 tokens per page snapshot.
          <br />
          Not 12,000.
        </span>
      </motion.h1>

      {/* Subheadline */}
      <motion.p
        {...fadeUp(0.1)}
        className="mt-5 max-w-lg text-base sm:text-lg text-white/40 leading-relaxed"
      >
        grip is a CDP-native browser SDK for AI agents. It hands your agent a
        semantic page snapshot — interactive elements and visible text — instead
        of raw HTML. No Playwright bloat.
      </motion.p>

      {/* CTAs */}
      <motion.div {...fadeUp(0.15)} className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <a
          href="#install"
          className="flex items-center gap-2 rounded-full bg-white px-5 py-2.5 text-sm font-medium text-black hover:bg-white/90 transition-colors"
        >
          Get started <ArrowRight size={13} />
        </a>
        <a
          href="https://github.com/84yk8btb9f-prog/grip-browser"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-5 py-2.5 text-sm text-white/70 hover:bg-white/[0.08] hover:text-white transition-colors"
        >
          View on GitHub
        </a>
      </motion.div>

      {/* Proof strip — live badges, real numbers */}
      <motion.div {...fadeUp(0.2)} className="mt-6 flex flex-wrap items-center justify-center gap-2">
        <a
          href="https://pypi.org/project/grip-browser/"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="grip-browser on PyPI"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="https://img.shields.io/pypi/v/grip-browser?style=flat-square&labelColor=1a1a1a&color=2e2e2e"
            alt="PyPI version"
            height={20}
          />
        </a>
        <a
          href="https://pypi.org/project/grip-browser/"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="grip-browser downloads on PyPI"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="https://img.shields.io/pypi/dm/grip-browser?style=flat-square&labelColor=1a1a1a&color=2e2e2e"
            alt="PyPI monthly downloads"
            height={20}
          />
        </a>
        <a
          href="https://github.com/nikolas-sapa/grip-browser"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="grip-browser stars on GitHub"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="https://img.shields.io/github/stars/nikolas-sapa/grip-browser?style=flat-square&labelColor=1a1a1a&color=2e2e2e"
            alt="GitHub stars"
            height={20}
          />
        </a>
      </motion.div>

      {/* Hero visual — animated snapshot demo */}
      <motion.div {...fadeUp(0.25)} className="mt-14 w-full">
        <HeroVisual />
      </motion.div>
    </section>
  );
}
