import { a11yInversion, A11Y_INVERSION_MECHANISM, BENCHMARK, PACKAGE } from "@/lib/metrics";

export function A11yInversion() {
  return (
    <section id="a11y" className="relative px-6 py-20 sm:py-28">
      <div className="mx-auto max-w-3xl">
        <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
          One page, {BENCHMARK.date}
        </p>

        <h2 className="mt-5 text-[clamp(1.75rem,4vw,2.5rem)] font-semibold leading-[1.1] tracking-[-0.03em] text-balance">
          The accessibility tree came out larger than the markup it was compressing.
        </h2>

        <div className="mt-10 overflow-hidden rounded-xl border border-border">
          <table className="w-full text-[15px]">
            <thead>
              <tr className="border-b border-border">
                <th className="px-5 py-3 text-left font-mono text-[11px] font-normal uppercase tracking-[0.06em] text-muted-foreground">
                  {a11yInversion.page}
                </th>
                <th className="px-5 py-3 text-right font-mono text-[11px] font-normal uppercase tracking-[0.06em] text-muted-foreground">
                  tokens
                </th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              <tr className="border-b border-border">
                <td className="px-5 py-3">Raw HTML</td>
                <td className="px-5 py-3 text-right">
                  {a11yInversion.rawHtml.toLocaleString("en-US")}
                </td>
              </tr>
              <tr className="border-b border-border bg-[var(--primary)]/[0.04]">
                <td className="px-5 py-3 font-medium">grip snapshot</td>
                <td className="px-5 py-3 text-right font-medium text-[var(--primary)]">
                  {a11yInversion.grip.toLocaleString("en-US")}
                </td>
              </tr>
              <tr>
                <td className="px-5 py-3">Playwright MCP accessibility snapshot</td>
                <td className="px-5 py-3 text-right">
                  {a11yInversion.playwrightMcp.toLocaleString("en-US")}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p className="mt-5 text-[15px] leading-[1.65] text-muted-foreground">
          Same page, same machine, same encoder. Not marginally. Larger, by a factor of{" "}
          {a11yInversion.expansion}.
        </p>

        <p className="mt-6 text-[17px] leading-[1.6] text-foreground/90">
          {A11Y_INVERSION_MECHANISM}
        </p>

        <p className="mt-6 text-[15px] leading-[1.65] text-muted-foreground">
          This is not a Playwright defect, and it does not mean accessibility trees are the
          wrong call. On {a11yInversion.playwrightWins} of the {a11yInversion.totalPages}{" "}
          pages in this corpus Playwright MCP wins comfortably. It is the one page where it
          does not, and it is published here because it is the case that makes the popular
          one-liner stop being true.
        </p>

        <p className="mt-6 text-sm text-muted-foreground">
          Per-page table and method:{" "}
          <a
            href={PACKAGE.results.replace("RESULTS_AB.md", "RESULTS_COMPETITORS.md")}
            className="text-[var(--primary)] underline underline-offset-4"
          >
            {a11yInversion.doc}
          </a>
        </p>
      </div>
    </section>
  );
}
