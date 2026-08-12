import { ArrowRight } from "lucide-react";
import { CopyButton } from "@/components/copy-button";
import { GithubMark } from "@/components/icons";
import { Reveal } from "@/components/reveal";
import { Eyebrow, Lede, Method, SectionHeading } from "@/components/section";
import { PACKAGE, tests } from "@/lib/metrics";

const EXTRAS = [
  { command: "pip install grip-browser", note: "core" },
  { command: "pip install grip-browser[anthropic]", note: "with the Anthropic adapter" },
  { command: "pip install grip-browser[openai]", note: "with the OpenAI adapter" },
  { command: "pip install grip-browser[gemini]", note: "with the Gemini adapter" },
];

export function Install() {
  return (
    <section id="install" className="px-6 py-24 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <div className="grid gap-12 lg:grid-cols-12 lg:gap-16">
          <div className="min-w-0 lg:col-span-5">
            <Reveal>
              <Eyebrow index="10">Install</Eyebrow>
              <SectionHeading>Python 3.11+ and a Chrome.</SectionHeading>
              <Lede>
                grip finds Chrome or Chromium automatically, and falls back to the
                Chrome for Testing build that Playwright or Puppeteer already
                downloaded. Set CHROME_EXECUTABLE to override.
              </Lede>

              <div className="mt-8 flex flex-wrap gap-3">
                <a
                  href={PACKAGE.github}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex h-10 items-center gap-2 rounded-md bg-[var(--primary)] px-4 text-[13px] font-medium text-[var(--primary-foreground)] transition-colors hover:bg-[#0059d1] focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  <GithubMark className="size-3.5" />
                  Read the docs
                  <ArrowRight className="size-3.5" strokeWidth={2} />
                </a>
                <a
                  href={PACKAGE.pypi}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex h-10 items-center gap-2 rounded-md border border-border px-4 text-[13px] font-medium transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
                >
                  View on PyPI
                </a>
              </div>
            </Reveal>
          </div>

          <div className="min-w-0 lg:col-span-7">
            <Reveal delay={0.08}>
              <div className="overflow-hidden rounded-[12px] border border-border bg-card">
                {EXTRAS.map((extra) => (
                  <div
                    key={extra.command}
                    className="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0"
                  >
                    <code className="overflow-x-auto font-mono text-[13px] whitespace-nowrap">
                      <span className="text-muted-foreground select-none">$ </span>
                      {extra.command}
                    </code>
                    <span className="ml-auto hidden shrink-0 font-mono text-[11px] text-muted-foreground sm:inline">
                      {extra.note}
                    </span>
                    <CopyButton
                      value={extra.command}
                      label={`Copy: ${extra.command}`}
                    />
                  </div>
                ))}
              </div>
            </Reveal>

            <Reveal delay={0.1}>
              <p className="mt-4 text-[13px] leading-[1.65] text-muted-foreground">
                No Anthropic, OpenAI or Gemini key on hand? Pass{" "}
                <code className="font-mono text-[12.5px] text-foreground">
                  base_url
                </code>{" "}
                to the OpenAI adapter (or set{" "}
                <code className="font-mono text-[12.5px] text-foreground">
                  OPENAI_BASE_URL
                </code>
                ) and point it at any OpenAI-compatible endpoint: Ollama,
                vLLM, LM Studio, OpenRouter.
              </p>
            </Reveal>

            <Reveal delay={0.12}>
              <dl className="mt-6 grid grid-cols-3 gap-px overflow-hidden rounded-[12px] border border-border bg-border">
                {[
                  { label: "unit", value: tests.unit },
                  { label: "gripsearch", value: tests.gripsearch },
                  { label: "integration", value: tests.integration },
                ].map((row) => (
                  <div key={row.label} className="bg-background p-5">
                    <dd className="font-mono text-[22px] leading-none font-medium tabular-nums">
                      {row.value}
                    </dd>
                    <dt className="mt-2 text-[12px] text-muted-foreground">
                      {row.label} tests pass
                    </dt>
                  </div>
                ))}
              </dl>
            </Reveal>

            <Reveal delay={0.16}>
              <div className="mt-4">
                <Method>
                  Integration tests run against real Chrome over live network.
                  Counts are for the current branch and will move, so re-run them
                  rather than trusting the number.
                </Method>
              </div>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}
