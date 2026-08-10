"use client";

import { motion, useReducedMotion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { CopyButton } from "@/components/copy-button";
import { GithubMark } from "@/components/icons";
import { HeroVisual } from "@/components/hero-visual";
import { BENCHMARK, PACKAGE, VERSION, endToEnd } from "@/lib/metrics";

const EASE_OUT_EXPO = [0.16, 1, 0.3, 1] as const;

function Rise({ children, delay }: { children: React.ReactNode; delay: number }) {
  const reduced = useReducedMotion();
  if (reduced) return <>{children}</>;
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.8, delay, ease: EASE_OUT_EXPO }}
    >
      {children}
    </motion.div>
  );
}

export function Hero() {
  return (
    <section id="top" className="relative px-6 pt-32 pb-16 sm:pt-40 sm:pb-24">
      <div className="mx-auto grid max-w-6xl gap-12 lg:grid-cols-12 lg:gap-16">
        <div className="min-w-0 lg:col-span-6 lg:pt-6">
          <Rise delay={0}>
            <a
              href="#cost"
              className="inline-flex items-center gap-2 rounded-full border border-border py-1 pr-3 pl-1 text-[12px] text-muted-foreground transition-colors hover:border-[var(--primary)] hover:text-foreground"
            >
              <span className="rounded-full bg-[var(--primary)] px-2 py-0.5 font-mono text-[11px] text-[var(--primary-foreground)] tabular-nums">
                v{VERSION}
              </span>
              Three-way benchmark, {BENCHMARK.date}
              <ArrowRight className="size-3" strokeWidth={2} />
            </a>
          </Rise>

          <Rise delay={0.06}>
            <h1 className="mt-8 max-w-[16ch] text-[clamp(2.5rem,6vw,4rem)] leading-[1.03] font-semibold tracking-[-0.04em] text-balance">
              A browser your agent can afford to look at.
            </h1>
          </Rise>

          <Rise delay={0.12}>
            <p className="mt-6 max-w-lg text-[17px] leading-[1.6] text-muted-foreground">
              grip is a CDP-native Python SDK. Point it at a page and your model
              gets the interactive elements and the visible text, indexed and
              fuzzy-matchable, small enough to keep in context for a whole run.
              No Playwright, no Puppeteer, no wrapper binary.
            </p>
          </Rise>

          <Rise delay={0.18}>
            <div className="mt-8 flex items-baseline gap-4 border-l-2 border-[var(--primary)] pl-4">
              <span className="font-mono text-[30px] leading-none font-medium tracking-[-0.03em] tabular-nums">
                {endToEnd.median}
              </span>
              <span className="text-[13px] leading-[1.5] text-muted-foreground">
                {endToEnd.what}.{" "}
                <span className="font-mono tabular-nums">
                  {endToEnd.repeatRuns}
                </span>{" "}
                across repeat runs of the benchmark.
              </span>
            </div>
          </Rise>

          <Rise delay={0.24}>
            <div className="mt-10 flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-1 rounded-md border border-border bg-card py-1 pr-1 pl-4">
                <code className="font-mono text-[13px] whitespace-nowrap">
                  <span className="text-muted-foreground select-none">$ </span>
                  {PACKAGE.pip}
                </code>
                <CopyButton value={PACKAGE.pip} label="Copy install command" />
              </div>

              <a
                href={PACKAGE.github}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-10 items-center gap-2 rounded-md border border-border px-4 text-[13px] font-medium transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
              >
                <GithubMark className="size-3.5" />
                Source
              </a>
            </div>
          </Rise>
        </div>

        <div className="min-w-0 lg:col-span-6">
          <Rise delay={0.2}>
            <HeroVisual />
          </Rise>
        </div>
      </div>
    </section>
  );
}
