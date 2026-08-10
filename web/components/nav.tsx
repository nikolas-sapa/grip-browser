"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { PACKAGE, VERSION } from "@/lib/metrics";
import { GithubMark } from "@/components/icons";
import { ThemeToggle } from "@/components/theme-toggle";

const LINKS = [
  { href: "#cost", label: "Token cost" },
  { href: "#breakdown", label: "Breakdown" },
  { href: "#code", label: "Code" },
  { href: "#limits", label: "Limits" },
];

export function Nav() {
  // The border only earns its place once content is behind the bar.
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={cn(
        "fixed inset-x-0 top-0 z-50 h-14 backdrop-blur-md transition-colors duration-300",
        scrolled
          ? "border-b border-border bg-background/80"
          : "border-b border-transparent bg-transparent",
      )}
    >
      <div className="mx-auto flex h-full max-w-6xl items-center gap-6 px-6">
        <a href="#top" className="flex items-baseline gap-2">
          <span className="text-[15px] font-semibold tracking-[-0.02em]">grip</span>
          <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
            v{VERSION}
          </span>
        </a>

        <nav className="ml-auto hidden items-center gap-6 md:flex">
          {LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="text-[13px] text-muted-foreground transition-colors hover:text-foreground"
            >
              {link.label}
            </a>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-1 md:ml-0">
          <a
            href={PACKAGE.github}
            target="_blank"
            rel="noreferrer"
            aria-label="grip on GitHub"
            className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            <GithubMark className="size-4" />
          </a>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
