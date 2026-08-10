import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Small mono eyebrow. Numbering the sections gives the page a spine without
 * another heading level competing with the h2. */
export function Eyebrow({ index, children }: { index: string; children: ReactNode }) {
  return (
    <p className="flex items-center gap-3 font-mono text-[11px] tracking-[0.08em] text-muted-foreground uppercase">
      <span className="text-[var(--primary)] tabular-nums">{index}</span>
      {children}
    </p>
  );
}

export function SectionHeading({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <h2
      className={cn(
        "mt-4 text-[clamp(1.75rem,3.4vw,2.5rem)] leading-[1.1] font-semibold tracking-[-0.03em] text-balance",
        className,
      )}
    >
      {children}
    </h2>
  );
}

export function Lede({ children }: { children: ReactNode }) {
  return (
    <p className="mt-4 max-w-xl text-[15px] leading-[1.65] text-muted-foreground">
      {children}
    </p>
  );
}

/** Footnotes carry the method. Every measured claim on the page has one. */
export function Method({ children }: { children: ReactNode }) {
  return (
    <p className="font-mono text-[11px] leading-[1.7] text-muted-foreground">
      {children}
    </p>
  );
}
