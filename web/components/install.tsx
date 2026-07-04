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
        transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] }}
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
        <div className="relative flex items-center rounded-xl border border-white/[0.08] bg-[#111113] px-5 py-4 font-mono text-sm text-white/70">
          <span className="text-white/20 mr-3 select-none">$</span>
          <span className="flex-1 text-left">{VARIANTS[active].cmd}</span>
          <button
            onClick={copy}
            aria-label="Copy install command"
            className="ml-4 flex items-center justify-center w-7 h-7 rounded-lg border border-white/10 hover:bg-white/10 transition-colors"
          >
            {copied
              ? <Check size={12} className="text-emerald-400" />
              : <Copy size={12} className="text-white/40" />
            }
          </button>
        </div>

        <p className="mt-4 text-[11px] text-white/25 font-mono">
          requires Python 3.11+ · Chrome/Chromium installed
        </p>

        <div className="mt-10 flex flex-wrap justify-center gap-3">
          <a
            href="https://github.com/84yk8btb9f-prog/grip-browser"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-full border border-white/10 bg-white/[0.04] px-5 py-2.5 text-sm text-white/70 hover:bg-white/[0.08] hover:text-white transition-colors"
          >
            View on GitHub
          </a>
          <a
            href="https://github.com/84yk8btb9f-prog/grip-browser#readme"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-full bg-white px-5 py-2.5 text-sm font-medium text-black hover:bg-white/90 transition-colors"
          >
            Read the README
          </a>
        </div>
      </motion.div>
    </section>
  );
}
