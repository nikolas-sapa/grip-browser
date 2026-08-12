import { ArrowRight } from "lucide-react";
import { CopyButton } from "@/components/copy-button";
import { Reveal } from "@/components/reveal";
import { Eyebrow, Lede, Method, SectionHeading } from "@/components/section";
import { PACKAGE } from "@/lib/metrics";

const MCP_INSTALL = 'pip install "grip-browser[mcp]"';
const MCP_ADD = "claude mcp add grip -- grip-mcp";

const CLIENTS = ["Claude Code", "Claude Desktop", "Cursor"] as const;

export function Mcp() {
  return (
    <section id="mcp" className="px-6 py-24 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <div className="grid gap-12 lg:grid-cols-12 lg:gap-16">
          <div className="min-w-0 lg:col-span-5">
            <Reveal>
              <Eyebrow index="09">MCP server</Eyebrow>
              <SectionHeading>grip as a stdio MCP server.</SectionHeading>
              <Lede>
                `grip-mcp` exposes 19 tools over stdio: open, goto, snapshot,
                click, type, select, read, screenshot, run, list_tabs,
                switch_tab, close_tab, press, upload, links, popups_blocked,
                wait_for, hover and scroll. Eighteen of them need no LLM key
                at all — only `run` does.
              </Lede>
              <div className="mt-6 flex flex-wrap gap-2">
                {CLIENTS.map((client) => (
                  <span
                    key={client}
                    className="rounded-full border border-border px-3 py-1 font-mono text-[11px] text-muted-foreground"
                  >
                    {client}
                  </span>
                ))}
              </div>
            </Reveal>
          </div>

          <div className="min-w-0 lg:col-span-7">
            <Reveal delay={0.08}>
              <div className="overflow-hidden rounded-[12px] border border-border bg-card">
                {[MCP_INSTALL, MCP_ADD].map((command) => (
                  <div
                    key={command}
                    className="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0"
                  >
                    <code className="overflow-x-auto font-mono text-[13px] whitespace-nowrap">
                      <span className="text-muted-foreground select-none">$ </span>
                      {command}
                    </code>
                    <CopyButton value={command} label={`Copy: ${command}`} />
                  </div>
                ))}
              </div>
            </Reveal>

            <Reveal delay={0.14}>
              <a
                href={PACKAGE.mcpDoc}
                target="_blank"
                rel="noreferrer"
                className="mt-6 inline-flex items-center gap-2 text-[13px] font-medium text-foreground underline underline-offset-2 hover:text-[var(--primary)]"
              >
                Full tool reference and Claude Desktop / Cursor config
                <ArrowRight className="size-3.5" strokeWidth={2} />
              </a>
            </Reveal>

            <Reveal delay={0.18}>
              <div className="mt-6">
                <Method>
                  One browser, one active page, per server process — there is
                  no multi-session registry. Run multiple `grip-mcp`
                  processes for concurrent sessions. Source: docs/mcp.md.
                </Method>
              </div>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}
