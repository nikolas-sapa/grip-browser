import { CopyButton } from "@/components/copy-button";
import { Reveal } from "@/components/reveal";
import { Eyebrow, Lede, Method, SectionHeading } from "@/components/section";

// Descriptions lifted verbatim from grip/cli.py's argparse help strings —
// this section cannot drift from the actual CLI surface.
const COMMANDS = [
  { cmd: "grip open URL", help: "Launch, navigate, print snapshot, exit." },
  { cmd: "grip snapshot URL", help: "One-shot open+snapshot+print (pipe-friendly)." },
  { cmd: "grip read URL", help: "Print citable prose blocks for a URL." },
  { cmd: "grip screenshot URL -o out.jpg", help: "Save a screenshot and print its token estimate." },
  { cmd: "grip run GOAL --url URL", help: "One-shot autonomous run via Browser.run()." },
  { cmd: "grip doctor", help: "Check the local install: Python version, Chrome, grip version." },
] as const;

export function Cli() {
  return (
    <section id="cli" className="px-6 py-24 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <div className="grid gap-12 lg:grid-cols-12 lg:gap-16">
          <div className="min-w-0 lg:col-span-5">
            <Reveal>
              <Eyebrow index="06">The CLI</Eyebrow>
              <SectionHeading>Six commands, zero new dependencies.</SectionHeading>
              <Lede>
                `grip` ships as a console script on top of stdlib argparse —
                no extra install, no framework. It is the fastest way to see
                what an agent sees before writing a line of Python.
              </Lede>
            </Reveal>
          </div>

          <div className="min-w-0 lg:col-span-7">
            <Reveal delay={0.08}>
              <div className="overflow-hidden rounded-[12px] border border-border bg-card">
                {COMMANDS.map((c) => (
                  <div
                    key={c.cmd}
                    className="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0"
                  >
                    <code className="overflow-x-auto font-mono text-[13px] whitespace-nowrap">
                      <span className="text-muted-foreground select-none">$ </span>
                      {c.cmd}
                    </code>
                    <span className="ml-auto hidden shrink-0 text-right text-[12px] text-muted-foreground sm:inline">
                      {c.help}
                    </span>
                    <CopyButton value={c.cmd} label={`Copy: ${c.cmd}`} />
                  </div>
                ))}
              </div>
            </Reveal>

            <Reveal delay={0.14}>
              <div className="mt-6">
                <Method>
                  Help text quoted from grip/cli.py&rsquo;s argparse
                  definitions, so this list cannot say more than the CLI
                  actually does. `--json` on the top-level parser switches any
                  of these to machine-readable output.
                </Method>
              </div>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}
