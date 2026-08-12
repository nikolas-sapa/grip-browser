import { TriangleAlert } from "lucide-react";
import { Reveal } from "@/components/reveal";
import { Eyebrow, Lede, Method, SectionHeading } from "@/components/section";
import {
  PACKAGE,
  TASK_BENCHMARK,
  TASK_BENCHMARK_CAVEAT,
  TASK_BENCHMARK_FIX,
} from "@/lib/metrics";

/**
 * This is not a victory lap. The section leads with the loss because the
 * sequence (lost, traced, fixed, re-run) is what makes the 100% credible —
 * a bare "100%" with the caveats in a footnote is the thing that gets a
 * project called dishonest, so the caveat card is full-weight, not small print
 * at the bottom.
 */
export function TaskSuccess() {
  return (
    <section id="task-success" className="border-y border-border bg-card px-6 py-24 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <div className="grid gap-12 lg:grid-cols-12 lg:gap-16">
          <div className="min-w-0 lg:col-span-5">
            <Reveal>
              <Eyebrow index="04">Task success</Eyebrow>
              <SectionHeading>
                grip lost the first run. Then it fixed the reason and won the
                re-run.
              </SectionHeading>
              <Lede>
                Not a token count this time: a real model in the loop,
                scored on whether a 30-task corpus of forms, SPAs and
                multi-step wizards actually got done.
              </Lede>
            </Reveal>

            <Reveal delay={0.1}>
              <div className="mt-8 flex flex-wrap items-baseline gap-x-8 gap-y-4">
                <div>
                  <div className="font-mono text-[30px] leading-none font-medium tracking-[-0.03em] tabular-nums">
                    {TASK_BENCHMARK.postFix.grip}
                  </div>
                  <p className="mt-2 text-[12px] text-muted-foreground">
                    grip, post-fix ({TASK_BENCHMARK.postFix.pct})
                  </p>
                </div>
                <div>
                  <div className="font-mono text-[30px] leading-none font-medium tracking-[-0.03em] text-muted-foreground tabular-nums">
                    {TASK_BENCHMARK.browseruse.score}
                  </div>
                  <p className="mt-2 text-[12px] text-muted-foreground">
                    browser-use ({TASK_BENCHMARK.browseruse.pct})
                  </p>
                </div>
                <div className="w-full border-t border-dashed border-border pt-3 sm:w-auto sm:border-0 sm:pt-0">
                  <div className="font-mono text-[15px] leading-none font-medium text-muted-foreground tabular-nums">
                    {TASK_BENCHMARK.firstRun.grip}
                  </div>
                  <p className="mt-2 text-[12px] text-muted-foreground">
                    grip, first run ({TASK_BENCHMARK.firstRun.pct}) — before the fix
                  </p>
                </div>
              </div>
            </Reveal>
          </div>

          <div className="min-w-0 lg:col-span-7">
            <Reveal delay={0.08}>
              <div className="overflow-hidden rounded-[12px] border border-border">
                <div className="grid grid-cols-3 gap-px bg-border text-[12px]">
                  <div className="bg-background px-3 py-2.5 font-mono text-[10px] tracking-[0.06em] text-muted-foreground uppercase">
                    Category
                  </div>
                  <div className="bg-background px-3 py-2.5 text-right font-mono text-[10px] tracking-[0.06em] text-muted-foreground uppercase">
                    grip
                  </div>
                  <div className="bg-background px-3 py-2.5 text-right font-mono text-[10px] tracking-[0.06em] text-muted-foreground uppercase">
                    browser-use
                  </div>
                  {TASK_BENCHMARK.categories.map((c) => (
                    <div key={c.label} className="contents">
                      <div className="bg-background px-3 py-2.5 font-mono text-[12px]">
                        {c.label}
                      </div>
                      <div className="bg-background px-3 py-2.5 text-right font-mono text-[12px] text-[var(--primary)] tabular-nums">
                        {c.grip}
                      </div>
                      <div className="bg-background px-3 py-2.5 text-right font-mono text-[12px] text-muted-foreground tabular-nums">
                        {c.browseruse}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </Reveal>

            <Reveal delay={0.12}>
              <div className="mt-6 rounded-[12px] border border-border bg-background p-6">
                <h3 className="text-[15px] font-medium tracking-[-0.01em]">
                  The SPA shutout, and the fix
                </h3>
                <p className="mt-3 text-[13.5px] leading-[1.7] text-muted-foreground">
                  {TASK_BENCHMARK_FIX}
                </p>
              </div>
            </Reveal>

            <Reveal delay={0.16}>
              <div className="mt-6 rounded-[12px] border border-[var(--warning)]/40 bg-background p-6">
                <div className="flex items-center gap-2">
                  <TriangleAlert
                    className="size-4 shrink-0 text-[var(--warning)]"
                    strokeWidth={1.75}
                  />
                  <h3 className="text-[15px] font-medium tracking-[-0.01em]">
                    Read this before the 100%
                  </h3>
                </div>
                <p className="mt-3 text-[13.5px] leading-[1.7] text-muted-foreground">
                  {TASK_BENCHMARK_CAVEAT}
                </p>
              </div>
            </Reveal>

            <Reveal delay={0.2}>
              <div className="mt-6">
                <Method>
                  On the {TASK_BENCHMARK.speed.n} tasks both arms completed,
                  grip ran a median{" "}
                  <span className="text-foreground">
                    {TASK_BENCHMARK.speed.medianOfRatios} faster
                  </span>{" "}
                  (range {TASK_BENCHMARK.speed.low} to {TASK_BENCHMARK.speed.high}) and,
                  on the {TASK_BENCHMARK.cost.n} with a recorded cost, a median{" "}
                  <span className="text-foreground">
                    {TASK_BENCHMARK.cost.medianOfRatios} cheaper
                  </span>{" "}
                  (range {TASK_BENCHMARK.cost.low} to {TASK_BENCHMARK.cost.high}
                  ) — as billed through the CLI path both arms used, not
                  content-only API pricing. Source:{" "}
                  <a
                    href={PACKAGE.taskBenchmark}
                    target="_blank"
                    rel="noreferrer"
                    className="text-foreground underline underline-offset-2 hover:text-[var(--primary)]"
                  >
                    {TASK_BENCHMARK.doc}
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
