import { Minus } from "lucide-react";
import { Reveal } from "@/components/reveal";
import { Eyebrow, Lede, Method, SectionHeading } from "@/components/section";
import { limits } from "@/lib/metrics";

export function Limits() {
  return (
    <section id="limits" className="border-y border-border bg-card px-6 py-24 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <div className="grid gap-12 lg:grid-cols-12 lg:gap-16">
          <div className="min-w-0 lg:col-span-5">
            <Reveal>
              <Eyebrow index="09">Limits</Eyebrow>
              <SectionHeading>What grip will not do for you.</SectionHeading>
              <Lede>
                The README and the security policy are candid about the edges of
                this library. A landing page that quietly widened them would be
                the least useful thing on the site.
              </Lede>
              <div className="mt-6 inline-flex items-center gap-2 rounded-full border border-[var(--warning)]/40 px-3 py-1">
                <span className="size-1.5 rounded-full bg-[var(--warning)]" />
                <span className="font-mono text-[11px] text-muted-foreground">
                  unmeasured means unclaimed
                </span>
              </div>
            </Reveal>
          </div>

          <div className="min-w-0 lg:col-span-7">
            <ul className="divide-y divide-border border-y border-border">
              {limits.map((limit, i) => (
                <li key={limit.title}>
                  <Reveal delay={Math.min(i, 3) * 0.05} className="flex gap-4 py-6">
                    <Minus
                      className="mt-1 size-4 shrink-0 text-muted-foreground"
                      strokeWidth={2}
                    />
                    <div>
                      <h3 className="text-[15px] font-medium tracking-[-0.01em]">
                        {limit.title}
                      </h3>
                      <p className="mt-2 text-[13.5px] leading-[1.7] text-muted-foreground">
                        {limit.body}
                      </p>
                    </div>
                  </Reveal>
                </li>
              ))}
            </ul>

            <Reveal delay={0.2}>
              <div className="mt-8">
                <Method>
                  Cold-start time, memory, requests per second, challenge solve
                  rates and any token figure for another tool are not measured
                  here, so none of them appear anywhere on this page.
                </Method>
              </div>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}
