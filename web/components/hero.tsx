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
      {/* Radial ambient glow */}
      <div
        className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full pointer-events-none"
        style={{ background: "radial-gradient(circle, rgba(255,255,255,0.04) 0%, transparent 70%)" }}
      />

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
        <span className="bg-gradient-to-b from-white to-white/60 bg-clip-text text-transparent">
          Browser SDK that thinks
          <br />
          in tokens.
        </span>
      </motion.h1>

      {/* Subheadline */}
      <motion.p
        {...fadeUp(0.1)}
        className="mt-5 max-w-lg text-base sm:text-lg text-white/40 leading-relaxed"
      >
        grip gives your AI agent a semantic page snapshot — interactive elements
        and visible text — in{" "}
        <span className="text-white/70 font-medium">~50 tokens</span>. Raw HTML costs 12,000.
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
          href="https://github.com/nikolassapalidis/agentbrowser"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-5 py-2.5 text-sm text-white/70 hover:bg-white/[0.08] hover:text-white transition-colors"
        >
          View on GitHub
        </a>
      </motion.div>

      {/* Hero visual — animated snapshot demo */}
      <motion.div {...fadeUp(0.2)} className="mt-14 w-full">
        <HeroVisual />
      </motion.div>
    </section>
  );
}
