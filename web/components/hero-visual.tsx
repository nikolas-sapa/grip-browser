"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence, useInView } from "framer-motion";
import { useRef } from "react";

const ELEMENTS = [
  { id: "inp:0", label: '"Search Amazon"', type: "inp" },
  { id: "btn:1", label: '"Go"', type: "btn" },
  { id: "btn:2", label: '"Sign in"', type: "btn" },
  { id: "lnk:3", label: '"Returns & Orders"', type: "lnk" },
  { id: "lnk:4", label: '"Cart"', type: "lnk" },
  { id: "btn:5", label: '"Today\'s Deals"', type: "btn" },
];

const CONTENT_LINE = "Delivering to New York — Shop deals in Electronics, Fashion...";

const TOKEN_COUNTS = [0, 4, 11, 18, 24, 31, 38, 50];

type ElementType = "inp" | "btn" | "lnk";

const TYPE_COLORS: Record<ElementType, string> = {
  inp: "text-sky-400",
  btn: "text-emerald-400",
  lnk: "text-violet-400",
};

export function HeroVisual() {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-40px" });

  const [phase, setPhase] = useState<"idle" | "scanning" | "done">("idle");
  const [visibleElements, setVisibleElements] = useState<number>(0);
  const [showContent, setShowContent] = useState(false);
  const [tokenCount, setTokenCount] = useState(0);
  const [scanY, setScanY] = useState(0);

  useEffect(() => {
    if (!inView) return;

    let t: ReturnType<typeof setTimeout>;

    // Start scanning after brief pause
    t = setTimeout(() => {
      setPhase("scanning");

      // Animate scan line
      const scanDuration = 900;
      const start = performance.now();
      const animate = (now: number) => {
        const progress = Math.min((now - start) / scanDuration, 1);
        setScanY(progress * 100);
        if (progress < 1) requestAnimationFrame(animate);
      };
      requestAnimationFrame(animate);

      // Reveal elements with stagger
      ELEMENTS.forEach((_, i) => {
        setTimeout(() => {
          setVisibleElements(i + 1);
          setTokenCount(TOKEN_COUNTS[i + 1]);
        }, 400 + i * 160);
      });

      // Show content line
      setTimeout(() => setShowContent(true), 400 + ELEMENTS.length * 160 + 100);

      // Final token count
      setTimeout(() => {
        setTokenCount(50);
        setPhase("done");
      }, 400 + ELEMENTS.length * 160 + 400);
    }, 500);

    return () => clearTimeout(t);
  }, [inView]);

  // Loop the animation
  useEffect(() => {
    if (phase !== "done") return;
    const t = setTimeout(() => {
      setPhase("idle");
      setVisibleElements(0);
      setShowContent(false);
      setTokenCount(0);
      setScanY(0);
      setTimeout(() => setPhase("scanning"), 200);

      // Re-run reveal
      ELEMENTS.forEach((_, i) => {
        setTimeout(() => {
          setVisibleElements(i + 1);
          setTokenCount(TOKEN_COUNTS[i + 1]);
        }, 400 + i * 160);
      });
      setTimeout(() => setShowContent(true), 400 + ELEMENTS.length * 160 + 100);
      setTimeout(() => {
        setTokenCount(50);
        setPhase("done");
      }, 400 + ELEMENTS.length * 160 + 400);
    }, 3200);

    return () => clearTimeout(t);
  }, [phase]);

  return (
    <div ref={ref} className="w-full max-w-2xl mx-auto select-none">
      {/* Browser chrome wrapper */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] }}
        className="rounded-2xl border border-white/[0.1] bg-[#0d0d0f] overflow-hidden shadow-[0_0_0_1px_rgba(255,255,255,0.04),0_32px_64px_rgba(0,0,0,0.6)]"
      >
        {/* Title bar */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-white/[0.06] bg-white/[0.02]">
          <div className="flex gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-white/10" />
            <span className="w-2.5 h-2.5 rounded-full bg-white/10" />
            <span className="w-2.5 h-2.5 rounded-full bg-white/10" />
          </div>
          {/* URL bar */}
          <div className="flex-1 flex items-center gap-2 rounded-md border border-white/[0.06] bg-white/[0.03] px-3 py-1">
            <span className="text-[10px] font-mono text-white/20">https://</span>
            <span className="text-[10px] font-mono text-white/50">amazon.com</span>
            {phase === "scanning" && (
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: [0.4, 1, 0.4] }}
                transition={{ duration: 0.8, repeat: Infinity }}
                className="ml-auto text-[9px] font-mono text-sky-400/60"
              >
                scanning…
              </motion.span>
            )}
            {phase === "done" && (
              <motion.span
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="ml-auto text-[9px] font-mono text-emerald-400/60"
              >
                indexed
              </motion.span>
            )}
          </div>
        </div>

        {/* Snapshot output */}
        <div className="relative px-5 py-5 min-h-[220px] overflow-hidden font-mono text-[12px] leading-relaxed">

          {/* PAGE header */}
          <div className="mb-3">
            <span className="text-white/20">PAGE: </span>
            <span className="text-white/50">Amazon.com</span>
          </div>

          {/* INTERACTIVE section */}
          <div className="mb-1">
            <span className="text-white/20 text-[11px] tracking-widest uppercase">Interactive:</span>
          </div>
          <div className="space-y-1 mb-3 pl-2">
            <AnimatePresence>
              {ELEMENTS.slice(0, visibleElements).map((el, i) => (
                <motion.div
                  key={el.id}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.25, ease: "easeOut" }}
                  className="flex items-baseline gap-2"
                >
                  <span className="text-white/20">[</span>
                  <span className={TYPE_COLORS[el.type as ElementType]}>{el.id}</span>
                  <span className="text-white/20">]</span>
                  <span className="text-white/40">{el.label}</span>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>

          {/* CONTENT section */}
          <AnimatePresence>
            {showContent && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.3 }}
              >
                <div className="mb-1">
                  <span className="text-white/20 text-[11px] tracking-widest uppercase">Content:</span>
                </div>
                <div className="pl-2 text-white/30 text-[11px] leading-relaxed max-w-[380px] truncate">
                  {CONTENT_LINE}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Token badge — bottom right */}
          <AnimatePresence>
            {tokenCount > 0 && (
              <motion.div
                initial={{ opacity: 0, scale: 0.85 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] }}
                className="absolute bottom-4 right-4 flex items-center gap-2"
              >
                {/* Pulsing dot */}
                {phase !== "done" && (
                  <span className="relative flex h-1.5 w-1.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
                    <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-400" />
                  </span>
                )}
                {phase === "done" && (
                  <span className="relative flex h-1.5 w-1.5">
                    <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-400" />
                  </span>
                )}
                <span className="text-[11px] font-mono">
                  <span className="text-emerald-400 font-semibold tabular-nums">{tokenCount}</span>
                  <span className="text-white/30"> tokens estimated</span>
                </span>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </motion.div>

      {/* Below: comparison callout */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={inView ? { opacity: 1 } : {}}
        transition={{ duration: 0.5, delay: 0.8 }}
        className="mt-4 flex items-center justify-center gap-2 text-[11px] font-mono text-white/25"
      >
        <span className="text-red-400/50 line-through">~12,000 tokens</span>
        <span>with raw HTML</span>
        <span className="text-white/10 mx-1">·</span>
        <span className="text-emerald-400/60">~50 tokens</span>
        <span>with grip</span>
      </motion.div>
    </div>
  );
}
