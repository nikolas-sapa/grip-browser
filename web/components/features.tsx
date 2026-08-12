import {
  Cable,
  Crosshair,
  Layers,
  ListChecks,
  Save,
  ScrollText,
  ShieldAlert,
  ShieldX,
  Upload,
  Waypoints,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Reveal } from "@/components/reveal";
import { Eyebrow, Lede, SectionHeading } from "@/components/section";

type Feature = {
  icon: LucideIcon;
  title: string;
  body: string;
  /** Column span at lg. Uneven on purpose: a uniform card grid reads as filler. */
  span: string;
};

const FEATURES: Feature[] = [
  {
    icon: Crosshair,
    title: "Fuzzy element matching",
    body: 'page.click("Go") resolves against the indexed snapshot. No selectors to write, and none to fix when the markup moves.',
    span: "lg:col-span-7",
  },
  {
    icon: Cable,
    title: "Pure CDP",
    body: "Straight onto the Chrome DevTools Protocol. No Playwright, no Puppeteer, no wrapper binary underneath.",
    span: "lg:col-span-5",
  },
  {
    icon: Layers,
    title: "Shadow DOM, fully traversed",
    body: "Web components and custom elements surface in the same snapshot as everything else.",
    span: "lg:col-span-4",
  },
  {
    icon: ShieldAlert,
    title: "Typed errors with a recovery",
    body: "ELEMENT_STALE, RATE_LIMITED, AUTH_REQUIRED and the rest arrive as values with a suggested action, not strings to parse.",
    span: "lg:col-span-4",
  },
  {
    icon: ScrollText,
    title: "Read mode",
    body: "read() isolates the main content and keeps the heading trail on every block, so a claim can be cited back to a location.",
    span: "lg:col-span-4",
  },
  {
    icon: Waypoints,
    title: "Concurrent pages, and a trace of all of them",
    body: "Every open() gets its own tab and its own CDP connection, so pages run in parallel. Every action is recorded with its timing and token cost and can be written out as a JSONL audit log.",
    span: "lg:col-span-12",
  },
  {
    icon: Upload,
    title: "File upload and download",
    body: "upload() resolves a file input the same way click() resolves a button, and enable_downloads() redirects a page's downloads to a directory grip watches instead of dropping them in the OS default.",
    span: "lg:col-span-6",
  },
  {
    icon: ListChecks,
    title: "Real <select> support",
    body: "select() matches an option by visible text first, then its value attribute, then a unique substring, and dispatches input/change — the same ladder click() and type() use for everything else.",
    span: "lg:col-span-6",
  },
  {
    icon: ShieldX,
    title: "Fail-closed by default",
    body: "NavigationPolicy blocks http(s) to private, loopback and link-local addresses, and the cloud metadata endpoints specifically, before a page ever loads. Private, file:// and popup access are opt-in per Browser, not on by default.",
    span: "lg:col-span-7",
  },
  {
    icon: Save,
    title: "Session persistence across runs",
    body: "save_session()/load_session() carry cookies and localStorage together, so a login survives closing the browser and starting a new one.",
    span: "lg:col-span-5",
  },
];

export function Features() {
  return (
    <section className="px-6 py-24 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <Reveal>
          <Eyebrow index="07">Capabilities</Eyebrow>
          <SectionHeading>Built for the loop, not for the test suite.</SectionHeading>
          <Lede>
            Everything here exists because an agent needed it mid-run: a page that
            changed under it, a component in a shadow root, an error it had to
            branch on.
          </Lede>
        </Reveal>

        <div className="mt-14 grid gap-px overflow-hidden rounded-[12px] border border-border bg-border lg:grid-cols-12">
          {FEATURES.map((feature, i) => (
            <Reveal
              key={feature.title}
              delay={Math.min(i, 4) * 0.05}
              className={`bg-background ${feature.span}`}
            >
              <div className="h-full p-6 sm:p-7">
                <feature.icon
                  className="size-4 text-muted-foreground"
                  strokeWidth={1.75}
                />
                <h3 className="mt-4 text-[15px] font-medium tracking-[-0.01em]">
                  {feature.title}
                </h3>
                <p className="mt-2 max-w-prose text-[13.5px] leading-[1.65] text-muted-foreground">
                  {feature.body}
                </p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
