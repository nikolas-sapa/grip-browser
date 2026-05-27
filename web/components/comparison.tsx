"use client";

import { motion } from "framer-motion";
import { Check, X, Minus } from "lucide-react";

type CellValue = true | false | "partial";

const ROWS: { label: string; grip: CellValue; playwright: CellValue; puppeteer: CellValue }[] = [
  { label: "~50 tokens per snapshot", grip: true, playwright: false, puppeteer: false },
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
        transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] }}
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
            className="grid grid-cols-4 border-b border-white/[0.05] last:border-0 hover:bg-white/[0.02] transition-colors"
          >
            <div className="px-4 py-3 text-xs text-white/50">{row.label}</div>
            <div className="px-4 py-3"><Cell value={row.grip} highlight /></div>
            <div className="px-4 py-3"><Cell value={row.playwright} /></div>
            <div className="px-4 py-3"><Cell value={row.puppeteer} /></div>
          </motion.div>
        ))}
      </div>
    </section>
  );
}
