import { GithubMark } from "@/components/icons";
import { PACKAGE, VERSION } from "@/lib/metrics";

const LINKS = [
  { href: PACKAGE.github, label: "GitHub" },
  { href: PACKAGE.pypi, label: "PyPI" },
  { href: `${PACKAGE.github}/blob/main/SECURITY.md`, label: "Security" },
  { href: `${PACKAGE.github}/blob/main/CONTRIBUTING.md`, label: "Contributing" },
  { href: `${PACKAGE.github}/tree/main/evaluation`, label: "Benchmarks" },
];

export function Footer() {
  return (
    <footer className="border-t border-border px-6 py-12">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 sm:flex-row sm:items-center">
        <div>
          <p className="flex items-baseline gap-2">
            <span className="text-[15px] font-semibold tracking-[-0.02em]">grip</span>
            <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
              v{VERSION}
            </span>
          </p>
          <p className="mt-2 text-[12px] text-muted-foreground">
            MIT licensed. Token-efficient, CDP-native browser SDK for AI agents.
          </p>
        </div>

        <nav className="flex flex-wrap items-center gap-x-6 gap-y-2 sm:ml-auto">
          {LINKS.map((link) => (
            <a
              key={link.label}
              href={link.href}
              target="_blank"
              rel="noreferrer"
              className="text-[13px] text-muted-foreground transition-colors hover:text-foreground"
            >
              {link.label}
            </a>
          ))}
          <a
            href={PACKAGE.github}
            target="_blank"
            rel="noreferrer"
            aria-label="grip on GitHub"
            className="text-muted-foreground transition-colors hover:text-foreground"
          >
            <GithubMark className="size-4" />
          </a>
        </nav>
      </div>
    </footer>
  );
}
