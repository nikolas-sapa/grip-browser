import { ShieldCheck } from "lucide-react";
import { Reveal } from "@/components/reveal";
import { Eyebrow, Lede, Method, SectionHeading } from "@/components/section";
import {
  DELTA_CAVEAT,
  DELTA_DEFECT,
  PACKAGE,
  deltaOnSameDocument as d,
} from "@/lib/metrics";

/**
 * The delta gets its own section with the condition stated in the heading, not
 * in a footnote. A blanket per-turn claim here is exactly the overstatement the
 * benchmark corrected, and the low end of the range is a live defect, so it is
 * given the same weight as the win.
 */
export function Delta() {
  return (
    <section id="delta" className="border-y border-border bg-card px-6 py-24 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <div className="grid gap-12 lg:grid-cols-12 lg:gap-16">
          <div className="min-w-0 lg:col-span-5">
            <Reveal>
              <Eyebrow index="03">The delta</Eyebrow>
              <SectionHeading>
                When an agent works inside one page, it stops paying to look
                twice.
              </SectionHeading>
              <Lede>
                Filling a form, driving an SPA, stepping through a wizard: on a
                same-document turn grip sends only what changed. Of the{" "}
                {d.totalTurns} turns in the benchmark, {d.turns} were
                same-document, and on those a repeat observation cost a median{" "}
                {d.median} less than re-sending the snapshot.
              </Lede>
              <p className="mt-6 font-mono text-[11px] text-muted-foreground tabular-nums">
                range {d.low} to {d.high}
              </p>
            </Reveal>
          </div>

          <div className="min-w-0 lg:col-span-7">
            <Reveal delay={0.08}>
              <div className="rounded-[12px] border border-border bg-background p-6">
                <h3 className="text-[15px] font-medium tracking-[-0.01em]">
                  Why the median across a whole run is only 1.0x
                </h3>
                <p className="mt-3 text-[13.5px] leading-[1.7] text-muted-foreground">
                  {DELTA_CAVEAT}
                </p>
              </div>
            </Reveal>

            <Reveal delay={0.14}>
              <div className="mt-6 rounded-[12px] border border-border bg-background p-6">
                <div className="flex items-center gap-2">
                  <ShieldCheck
                    className="size-4 shrink-0 text-[var(--success)]"
                    strokeWidth={1.75}
                  />
                  <h3 className="text-[15px] font-medium tracking-[-0.01em]">
                    The {d.low} end of that range was a defect, and it is guarded
                    now
                  </h3>
                </div>
                <p className="mt-3 text-[13.5px] leading-[1.7] text-muted-foreground">
                  {DELTA_DEFECT}
                </p>
              </div>
            </Reveal>

            <Reveal delay={0.18}>
              <div className="mt-6">
                <Method>
                  Median of the per-turn ratios, with the full observed range.
                  The top of the range comes from large content pages; the
                  single-digit end is a 13-element form whose full snapshot is
                  under 200 tokens to begin with, so there is little left to
                  save. Source:{" "}
                  <a
                    href={PACKAGE.results}
                    target="_blank"
                    rel="noreferrer"
                    className="text-foreground underline underline-offset-2 hover:text-[var(--primary)]"
                  >
                    benchmarks/RESULTS_AB.md
                  </a>
                  .
                </Method>
              </div>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}
