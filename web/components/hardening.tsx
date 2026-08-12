import { Plus } from "lucide-react";
import { Reveal } from "@/components/reveal";
import { Eyebrow, Lede, Method, SectionHeading } from "@/components/section";
import { tests } from "@/lib/metrics";

const HARDENING = [
  {
    title: "Silent failures, fixed",
    body: "click() reported success on a disabled, off-screen or overlay-covered element; it now hit-tests the point and names the occluder instead. type() bypassed React's and Vue's own value trackers and fired no key events, so a controlled input never saw the change. Every action snapshotted before the page had settled, so a click that navigated could return the pre-click page. page_error and prompt_injection were computed and then thrown away, so a blocked agent was told nothing.",
  },
  {
    title: "Security",
    body: "A typed password no longer reaches snapshot text, the model, or trace output. A page-authored element handle can no longer collide with grip's own or hijack selector resolution. A download landing outside the directory passed to enable_downloads() is dropped instead of returned.",
  },
  {
    title: "Correctness",
    body: 'click("Save") no longer matches "Save draft" — an exact match now wins outright over a fuzzy one. A stale ref from a previous document is rejected instead of silently resolving to whatever now sits at that index. A failed navigation (DNS, connection refused, timeout) no longer reports as success, and a browser crash is no longer reclassified as element-not-found, which used to loop an agent back into a dead connection.',
  },
  {
    title: "Newly visible",
    body: "Element state — disabled, required, checked, selected, value — is in the snapshot now, along with scroll position and page height. iframes surface as rows, closed shadow roots are readable (attachShadow is patched before navigation), and canvas and labelled SVG are candidates. Comboboxes are recognized as a distinct control. Inputs whose label is only sibling text — the httpbin case, previously addressable by ref alone — now resolve a label through a fallback chain: label-for or wrapping label, aria-label, placeholder, title, sibling text, then a humanized name or id.",
  },
  {
    title: "New capabilities",
    body: "JS dialogs are handled by policy instead of freezing the tab until timeout. wait_for(), hover() and scroll() (targeting the nearest scrollable ancestor) are new, and select() falls back to an open/re-snapshot/pick sequence for non-native comboboxes. A cookie-consent banner is dismissed conservatively before the caller's own snapshot, and a file chooser or popup can be intercepted and adopted. Viewport, device emulation and permission control — notifications and geolocation denied by default — are configurable per Browser.",
  },
  {
    title: "MCP server",
    body: "grip-mcp used to die on every call to any tool if an LLM SDK wasn't installed; the adapter is now resolved lazily, only for run. press, upload, links, popups_blocked, wait_for, hover and scroll are exposed, error-recovery hints reach the client, screenshot returns an image block instead of base64-as-text, and overlapping tool calls can no longer act on the wrong tab.",
  },
  {
    title: "Robustness",
    body: "The Chrome process and its temp profile no longer leak when kill() times out. The CDP timeout, previously fixed at 30 seconds, is overridable. The trace no longer grows unbounded, and Fetch.enable no longer pauses every subresource to police navigation.",
  },
] as const;

export function Hardening() {
  return (
    <section id="hardening" className="border-y border-border bg-card px-6 py-24 sm:py-32">
      <div className="mx-auto max-w-6xl">
        <div className="grid gap-12 lg:grid-cols-12 lg:gap-16">
          <div className="min-w-0 lg:col-span-5">
            <Reveal>
              <Eyebrow index="08">Hardening</Eyebrow>
              <SectionHeading>Shipped in 0.8.0.</SectionHeading>
              <Lede>
                A security and correctness pass across the whole surface: silent
                failures the agent was never told about, snapshot gaps, and
                everything MCP needed to stop dying on startup.
              </Lede>
            </Reveal>
          </div>

          <div className="min-w-0 lg:col-span-7">
            <ul className="divide-y divide-border border-y border-border">
              {HARDENING.map((item, i) => (
                <li key={item.title}>
                  <Reveal delay={Math.min(i, 3) * 0.05} className="flex gap-4 py-6">
                    <Plus
                      className="mt-1 size-4 shrink-0 text-muted-foreground"
                      strokeWidth={2}
                    />
                    <div>
                      <h3 className="text-[15px] font-medium tracking-[-0.01em]">
                        {item.title}
                      </h3>
                      <p className="mt-2 text-[13.5px] leading-[1.7] text-muted-foreground">
                        {item.body}
                      </p>
                    </div>
                  </Reveal>
                </li>
              ))}
            </ul>

            <Reveal delay={0.2}>
              <div className="mt-8">
                <Method>
                  {tests.unit} unit tests and {tests.integration} integration
                  tests against real Chrome pass on main; ruff and mypy are
                  clean.
                </Method>
              </div>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}
