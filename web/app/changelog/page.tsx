import { readFile } from "node:fs/promises";
import path from "node:path";
import type { Metadata } from "next";
import Markdown from "react-markdown";
import { Nav } from "@/components/nav";
import { Footer } from "@/components/footer";
import { Eyebrow, Lede, SectionHeading } from "@/components/section";
import { PACKAGE, VERSION } from "@/lib/metrics";

export const metadata: Metadata = {
  title: "Changelog — grip",
  description: `Every release of grip, currently v${VERSION}, with what changed and what it was measured against.`,
  alternates: { canonical: "/changelog" },
};

// The repo's CHANGELOG.md is the single source of truth. Rendering it at build
// time means a release can never ship a site that disagrees with it.
// ponytail: plain markdown render, no per-release parsing. Add version anchors
// if someone needs to link a single release.
async function changelog() {
  return readFile(path.join(process.cwd(), "..", "CHANGELOG.md"), "utf8");
}

export default async function ChangelogPage() {
  const source = await changelog();
  // Drop the file's title and Keep-a-Changelog preamble; the page heading and
  // lede above already say both, and repeating them reads as filler.
  const body = source.slice(Math.max(source.indexOf("\n## "), 0));

  return (
    <>
      <Nav />
      <main className="px-6 pt-32 pb-24">
        <div className="mx-auto max-w-3xl">
          <Eyebrow index="—">Changelog</Eyebrow>
          <SectionHeading>What changed, release by release.</SectionHeading>
          <Lede>
            Rendered from{" "}
            <a
              href={`${PACKAGE.github}/blob/main/CHANGELOG.md`}
              target="_blank"
              rel="noreferrer"
              className="text-foreground underline decoration-border underline-offset-4 hover:decoration-foreground"
            >
              CHANGELOG.md
            </a>{" "}
            in the repo, so it cannot drift from the released package.
          </Lede>

          <div className="mt-16 space-y-6 text-[14px] leading-[1.75] text-muted-foreground">
            <Markdown
              components={{
                h2: ({ children }) => (
                  <h2 className="mt-16 border-t border-border pt-8 text-[22px] font-semibold tracking-[-0.02em] text-foreground">
                    {/* Keep a Changelog writes versions as [0.8.1]; the
                        brackets are link syntax, not part of the version. */}
                    {typeof children === "string" ? children.replace(/[[\]]/g, "") : children}
                  </h2>
                ),
                h3: ({ children }) => (
                  <h3 className="mt-8 font-mono text-[11px] tracking-[0.08em] text-muted-foreground uppercase">
                    {children}
                  </h3>
                ),
                p: ({ children }) => <p className="mt-4">{children}</p>,
                ul: ({ children }) => (
                  <ul className="mt-4 space-y-3 border-l border-border pl-5">{children}</ul>
                ),
                ol: ({ children }) => (
                  <ol className="mt-4 list-decimal space-y-3 pl-5">{children}</ol>
                ),
                li: ({ children }) => <li>{children}</li>,
                strong: ({ children }) => (
                  <strong className="font-medium text-foreground">{children}</strong>
                ),
                code: ({ children }) => (
                  <code className="rounded-sm bg-card px-1 py-0.5 font-mono text-[12.5px] text-foreground">
                    {children}
                  </code>
                ),
                pre: ({ children }) => (
                  <pre className="mt-4 overflow-x-auto rounded-lg border border-border bg-card p-4 font-mono text-[12.5px]">
                    {children}
                  </pre>
                ),
                a: ({ href, children }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noreferrer"
                    className="text-foreground underline decoration-border underline-offset-4 hover:decoration-foreground"
                  >
                    {children}
                  </a>
                ),
                hr: () => <hr className="mt-12 border-border" />,
              }}
            >
              {body}
            </Markdown>
          </div>
        </div>
      </main>
      <Footer />
    </>
  );
}
