import { Reveal } from "@/components/reveal";
import { Eyebrow, Lede, Method, SectionHeading } from "@/components/section";
import { TokenChart } from "@/components/token-chart";
import { StatTileAsciiArrive } from "@/components/ui/stat-tile-ascii-arrive";
import type { Scenario } from "@/lib/metrics";
import {
  BENCHMARK,
  PACKAGE,
  contextWindow,
  endToEnd,
  scenarios,
} from "@/lib/metrics";

export function TokenCost() {
  return (
    <section id="cost" className="px-6 py-24 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <div className="grid gap-10 lg:grid-cols-12 lg:gap-16">
          <div className="min-w-0 lg:col-span-5">
            <Reveal>
              <Eyebrow index="01">Token cost</Eyebrow>
              <SectionHeading>
                The bill is the run,
                <br className="hidden sm:block" /> not the call.
              </SectionHeading>
              <Lede>
                An agent re-sends its history every turn, so what actually bills
                is the whole transcript. Four real scenarios, six turns each,
                driven against live sites through grip&rsquo;s own click and type
                calls.
              </Lede>
            </Reveal>

            <Reveal delay={0.08}>
              <div className="mt-10 rounded-[12px] border border-border p-5">
                <StatTileAsciiArrive
                  value={endToEnd.median}
                  label="End to end, cumulative prompt tokens"
                />
                <p className="mt-4 font-mono text-[11px] text-muted-foreground tabular-nums">
                  {endToEnd.repeatRuns} across repeat runs
                </p>
                <p className="mt-2 text-[13px] leading-[1.6] text-muted-foreground">
                  {endToEnd.what}. Median of the per-scenario ratios, not a ratio
                  of medians. Not a decimal, because the benchmark drives live
                  pages and they change under it.
                </p>
              </div>
            </Reveal>

            <Reveal delay={0.12}>
              <div className="mt-6 rounded-[12px] border border-border p-5">
                <p className="text-[13px] leading-[1.65] text-muted-foreground">
                  {contextWindow.note} The largest single raw-HTML observation
                  across {BENCHMARK.runs} runs was{" "}
                  <span className="font-mono text-foreground tabular-nums">
                    {contextWindow.largestRawHtmlTurn.toLocaleString()}
                  </span>{" "}
                  tokens; the largest grip observation was{" "}
                  <span className="font-mono text-foreground tabular-nums">
                    {contextWindow.largestGripObservation.toLocaleString()}
                  </span>
                  .
                </p>
              </div>
            </Reveal>
          </div>

          <div className="min-w-0 lg:col-span-7">
            <Reveal delay={0.12}>
              <figure className="rounded-[12px] border border-border bg-card p-4 sm:p-6">
                <figcaption className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-[13px] font-medium">
                    Cumulative prompt tokens across a {BENCHMARK.turnsPerScenario}
                    -turn run
                  </span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    four scenarios, lightest page first
                  </span>
                </figcaption>
                <TokenChart />
              </figure>
            </Reveal>

            <Reveal delay={0.16}>
              <div className="mt-6 overflow-hidden rounded-[12px] border border-border">
                <div className="grid grid-cols-4 gap-px bg-border">
                  <HeadCell>Scenario</HeadCell>
                  <HeadCell align="right">Peak prompt, raw</HeadCell>
                  <HeadCell align="right">Peak prompt, grip</HeadCell>
                  <HeadCell align="right">Run reduction</HeadCell>
                  {scenarios.map((s) => (
                    <Row key={s.label} scenario={s} />
                  ))}
                </div>
              </div>
            </Reveal>

            <Reveal delay={0.2}>
              <div className="mt-6 space-y-3">
                <Method>
                  Each chart point is a separate complete run, not a moment in
                  time. The x-axis is ordered by how much raw HTML the scenario
                  costs, so the grip curve reads flat at this scale rather than
                  zero: it runs from {scenarios[0].grip.toLocaleString()} to{" "}
                  {scenarios[scenarios.length - 1].grip.toLocaleString()} tokens
                  while raw HTML runs from{" "}
                  {scenarios[0].rawHtml.toLocaleString()} to{" "}
                  {scenarios[scenarios.length - 1].rawHtml.toLocaleString()}.
                </Method>
                <Method>
                  Per scenario the end-to-end reduction ranges {endToEnd.low} to{" "}
                  {endToEnd.high}. Peak prompt is what a single request carries;
                  no request ever carries the cumulative figure.
                </Method>
                <Method>
                  {BENCHMARK.command}, run of {BENCHMARK.date}.{" "}
                  {BENCHMARK.encoder}. Full method, defect log and repeat-run
                  variance in{" "}
                  <a
                    href={PACKAGE.results}
                    target="_blank"
                    rel="noreferrer"
                    className="text-foreground underline underline-offset-2 hover:text-[var(--primary)]"
                  >
                    {BENCHMARK.doc}
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

function HeadCell({
  children,
  align = "left",
}: {
  children: React.ReactNode;
  align?: "left" | "right";
}) {
  return (
    <div
      className={`bg-background px-3 py-2.5 font-mono text-[10px] tracking-[0.06em] text-muted-foreground uppercase ${
        align === "right" ? "text-right" : ""
      }`}
    >
      {children}
    </div>
  );
}

function Row({ scenario }: { scenario: Scenario }) {
  return (
    <>
      <div className="bg-background px-3 py-2.5 font-mono text-[12px]">
        {scenario.label}
      </div>
      <div className="bg-background px-3 py-2.5 text-right font-mono text-[12px] text-muted-foreground tabular-nums">
        {scenario.peakRawHtml.toLocaleString()}
      </div>
      <div className="bg-background px-3 py-2.5 text-right font-mono text-[12px] tabular-nums">
        {scenario.peakGrip.toLocaleString()}
      </div>
      <div className="bg-background px-3 py-2.5 text-right font-mono text-[12px] text-[var(--primary)] tabular-nums">
        {scenario.ratio}
      </div>
    </>
  );
}
