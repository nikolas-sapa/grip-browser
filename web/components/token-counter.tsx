"use client";

import { useEffect, useRef, useState } from "react";
import { useInView, animate } from "framer-motion";

function AnimatedNumber({
  target,
  duration = 1.5,
  className,
}: {
  target: number;
  duration?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-50px" });
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    if (!inView) return;
    const controls = animate(0, target, {
      duration,
      ease: [0.16, 1, 0.3, 1] as [number, number, number, number],
      onUpdate: (v) => setDisplay(Math.round(v)),
    });
    return controls.stop;
  }, [inView, target, duration]);

  return (
    <span ref={ref} className={className}>
      {display.toLocaleString()}
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
      <div className="flex items-center justify-center">
        <span className="text-[10px] font-mono text-white/20 px-2">vs</span>
      </div>

      {/* grip card */}
      <div className="flex-1 rounded-2xl border border-white/20 bg-white/[0.05] p-5 text-center relative overflow-hidden">
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
