"use client";

import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";

type Line = { kind: "key" | "el" | "text" | "blank"; text: string; tag?: string };

// The literal shape of `snapshot()` output — the thing the model actually sees.
// Kept as data rather than a <pre> string so each row can carry its own colour
// role and animate in as the index is built.
const SNAPSHOT: Line[] = [
  { kind: "key", text: "PAGE: Hacker News" },
  { kind: "key", text: "URL:  https://news.ycombinator.com/" },
  { kind: "blank", text: "" },
  { kind: "key", text: "INTERACTIVE:" },
  { kind: "el", tag: "[inp:0]", text: '"Search"  (placeholder)' },
  { kind: "el", tag: "[btn:1]", text: '"Go"' },
  { kind: "el", tag: "[lnk:2]", text: '"new"' },
  { kind: "el", tag: "[lnk:3]", text: '"past"' },
  { kind: "el", tag: "[lnk:4]", text: '"comments"' },
  { kind: "blank", text: "" },
  { kind: "key", text: "CONTENT:" },
  { kind: "text", text: "1.  Ask HN: what are you working on this week?" },
  { kind: "text", text: "2.  A tour of the Chrome DevTools Protocol" },
];

const EASE_OUT_EXPO = [0.16, 1, 0.3, 1] as const;

export function HeroVisual({ className }: { className?: string }) {
  const reduced = useReducedMotion();

  return (
    <div
      className={cn(
        "overflow-hidden rounded-[12px] border border-border bg-card",
        className,
      )}
    >
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <span className="font-mono text-[11px] text-muted-foreground">
          await page.snapshot()
        </span>
        <span className="ml-auto rounded-full border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground tabular-nums">
          what the model sees
        </span>
      </div>

      <div className="overflow-x-auto px-4 py-4">
        <pre className="min-w-max font-mono text-[12px] leading-[1.75]">
          {SNAPSHOT.map((line, i) => (
            <motion.div
              key={`${line.kind}-${i}`}
              initial={reduced ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.35 + i * 0.045, duration: 0.4, ease: EASE_OUT_EXPO }}
            >
              {line.kind === "blank" ? (
                " "
              ) : line.kind === "el" ? (
                <>
                  <span className="text-[var(--primary)]">{line.tag}</span>{" "}
                  <span className="text-foreground">{line.text}</span>
                </>
              ) : line.kind === "key" ? (
                <span className="text-muted-foreground">{line.text}</span>
              ) : (
                <span className="text-foreground">{line.text}</span>
              )}
            </motion.div>
          ))}
        </pre>
      </div>
    </div>
  );
}
