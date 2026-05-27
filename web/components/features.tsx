"use client";

import { motion } from "framer-motion";
import { Cpu, Layers, Target, ShieldAlert, Activity, Plug } from "lucide-react";

const FEATURES = [
  {
    icon: Cpu,
    title: "Pure CDP",
    description: "Speaks Chrome DevTools Protocol directly — no Playwright binary, no Puppeteer overhead.",
  },
  {
    icon: Target,
    title: "Fuzzy element matching",
    description: 'Click "Go" or type "search" — grip resolves to the real element. No CSS selectors.',
  },
  {
    icon: Layers,
    title: "Shadow DOM traversal",
    description: "Web components, Chrome extensions, custom elements — all discovered in the same snapshot.",
  },
  {
    icon: ShieldAlert,
    title: "Typed error recovery",
    description: "Every failure is a typed BrowserError with a suggested RecoveryAction. Your agent decides.",
  },
  {
    icon: Activity,
    title: "Token trace",
    description: "Every action recorded with timing and token cost. Export to JSONL for audit or replay.",
  },
  {
    icon: Plug,
    title: "LLM adapters",
    description: "OpenAI and Anthropic adapters ship out of the box. Bring your own via the LLMAdapter protocol.",
  },
];

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06 } },
};

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] } },
};

export function Features() {
  return (
    <section className="px-6 py-24 max-w-6xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-60px" }}
        transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] }}
        className="text-center mb-14"
      >
        <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight text-white">
          Built for agents, not browsers
        </h2>
        <p className="mt-3 text-white/40 max-w-md mx-auto text-sm sm:text-base">
          Every feature exists to save tokens, reduce hallucinations, and make agentic loops more reliable.
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
            className="rounded-2xl border border-white/[0.08] bg-white/[0.03] p-6 hover:border-white/[0.14] hover:bg-white/[0.05] transition-colors duration-200 group"
          >
            <div className="mb-4 flex items-center justify-center w-9 h-9 rounded-xl border border-white/10 bg-white/[0.06] group-hover:bg-white/10 transition-colors">
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
