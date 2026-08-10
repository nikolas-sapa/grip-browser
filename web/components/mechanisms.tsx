import { Reveal } from "@/components/reveal";
import { Eyebrow, Lede, Method, SectionHeading } from "@/components/section";
import { ChartBarDither } from "@/components/ui/chart-bar-dither";
import {
  PACKAGE,
  endToEnd,
  mechanismChartData,
  mechanisms,
  strippedTextCaveat,
} from "@/lib/metrics";

/**
 * The split is the story. Three mechanisms with three different shapes, never
 * averaged into one flattering number: a reader who runs their own
 * navigation-heavy benchmark has to find this page was straight with them.
 */
export function Mechanisms() {
  return (
    <section id="breakdown" className="px-6 py-24 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <Reveal>
          <Eyebrow index="02">Breakdown</Eyebrow>
          <SectionHeading>
            Where the {endToEnd.median} comes from.
          </SectionHeading>
          <Lede>
            Three mechanisms, measured separately because they behave
            differently. Compression is the broad win. Pruning is what keeps a
            long transcript from growing quadratically. The delta is the deep
            win, and only on the turns where an agent stays on one page.
          </Lede>
        </Reveal>

        <div className="mt-14 grid gap-10 lg:grid-cols-12 lg:gap-16">
          <div className="min-w-0 lg:col-span-5">
            <Reveal delay={0.08}>
              {/* Carded so the chart's fixed pixel width reads as a plate rather
                  than as an element floating in leftover column space. */}
              <div className="rounded-[12px] border border-border bg-card p-4 sm:p-6">
                <ChartBarDither
                  data={mechanismChartData}
                  title="Reduction by mechanism, median of the per-scenario ratios"
                />
              </div>
            </Reveal>
          </div>

          <div className="min-w-0 lg:col-span-7">
            <dl className="divide-y divide-border border-y border-border">
              {mechanisms.map((m, i) => (
                <div key={m.key}>
                  <Reveal delay={Math.min(i, 3) * 0.05} className="py-6">
                    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                      <dt className="text-[15px] font-medium tracking-[-0.01em]">
                        {m.label}
                      </dt>
                      <span className="font-mono text-[20px] font-medium text-[var(--primary)] tabular-nums">
                        {m.ratio.median}
                      </span>
                      <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
                        {m.ratio.low} to {m.ratio.high}
                      </span>
                      <span className="ml-auto font-mono text-[11px] text-muted-foreground">
                        {m.sub}
                      </span>
                    </div>
                    <dd className="mt-2 max-w-prose text-[13.5px] leading-[1.65] text-muted-foreground">
                      {m.note}
                    </dd>
                  </Reveal>
                </div>
              ))}
            </dl>

            <Reveal delay={0.2}>
              <div className="mt-8 space-y-3">
                <Method>
                  Compression is measured against raw HTML, which is the right
                  baseline if your agent would otherwise put the DOM in the
                  prompt. Against naively tag-stripped text the reduction is only{" "}
                  {strippedTextCaveat.ratio} ({strippedTextCaveat.source}),
                  because most of what grip removes is markup rather than words.
                  Use whichever baseline matches what you already send.
                </Method>
                <Method>
                  Every figure is a median of the per-scenario ratios with its
                  full range beside it. The end-to-end number is not the three
                  multiplied together: they act on different parts of the
                  transcript and overlap. Source:{" "}
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
