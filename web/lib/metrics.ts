/**
 * Every number the landing page is allowed to state lives here.
 *
 * Source: benchmarks/RESULTS_AB.md, run of 2026-08-10, grip 0.5.0. Four real
 * scenarios against live public sites, six agent turns each, tiktoken
 * cl100k_base. Re-running the benchmark moves these values; swap this file and
 * the whole page moves with it.
 *
 * Two rules this module enforces by shape:
 *  1. Every median ships with its range. A median with no range is how the
 *     first version of this page overstated the delta.
 *  2. All ratios are medians of the per-scenario ratios, never ratios of
 *     medians. The two are different statistics and mixing them silently is
 *     the other way this page went wrong.
 *
 * Not measured, therefore not claimed anywhere: cold-start time, memory,
 * requests per second, challenge solve rates, and any token figure for a named
 * competitor tool.
 */

export const VERSION = "0.5.0";

export const BENCHMARK = {
  date: "2026-08-10",
  encoder: "tiktoken cl100k_base",
  turnsPerScenario: 6,
  runs: 22,
  command: "python benchmarks/bench_agent_ab.py",
  doc: "benchmarks/RESULTS_AB.md",
} as const;

export const PACKAGE = {
  pip: "pip install grip-browser",
  pypi: "https://pypi.org/project/grip-browser/",
  github: "https://github.com/nikolas-sapa/grip-browser",
  results: "https://github.com/nikolas-sapa/grip-browser/blob/main/benchmarks/RESULTS_AB.md",
  taskBenchmark:
    "https://github.com/nikolas-sapa/grip-browser/blob/main/benchmarks/RESULTS_LLM_LOOP.md",
  mcpDoc: "https://github.com/nikolas-sapa/grip-browser/blob/main/docs/mcp.md",
} as const;

/**
 * Task-completion benchmark, a real model in the loop scoring whether a task
 * actually finished. Source: benchmarks/RESULTS_LLM_LOOP.md, 2026-08-11/12,
 * 30-task synthetic corpus (form/SPA/wizard), grip vs browser-use, both
 * driven through headless `claude -p`.
 *
 * The grip and browser-use numbers were NOT run on the same code at the same
 * time: browser-use's 30 rows predate grip's SPA fix (commit 2886d34); grip's
 * 30 rows are a full re-run after it. That is the load-bearing caveat and it
 * ships with every use of this object, not as an afterthought.
 */
export const TASK_BENCHMARK = {
  doc: "benchmarks/RESULTS_LLM_LOOP.md",
  firstRun: { grip: "20/30", pct: "66.7%" },
  postFix: { grip: "30/30", pct: "100%" },
  browseruse: { score: "24/30", pct: "80.0%" },
  categories: [
    { label: "form", grip: "10/10", browseruse: "10/10" },
    { label: "SPA", grip: "10/10", browseruse: "7/10" },
    { label: "wizard", grip: "10/10", browseruse: "7/10" },
  ],
  speed: { medianOfRatios: "19.13x", low: "1.65x", high: "49.95x", n: 24 },
  cost: { medianOfRatios: "7.17x", low: "0.85x", high: "21.80x", n: 22 },
} as const;

export const TASK_BENCHMARK_FIX =
  "The first full run: grip lost, 20/30 against browser-use's 24/30, on a 0/10 SPA shutout. gripIsCandidate() (grip/cdp/shadow.py) only admits elements with an interactive tag or ARIA role to the snapshot, so the SPA fixtures' non-semantic <div> click targets never got a ref to click. The fix (commit 2886d34, grip/page.py) adds a bounded DOMDebugger.getEventListeners probe, capped at 2 seconds, that only trusts a real click listener. grip was then re-run in full on the fixed code — the numbers above are that re-run.";

export const TASK_BENCHMARK_CAVEAT =
  "This is a limited-credibility result, not an independent audit. The fixtures are synthetic and self-hosted in grip's own repo, and the fix that produced grip's score was developed after seeing these exact failures — it is a general mechanism (any element with a click listener), not a fixture-specific patch, but it has only been validated against the fixtures it was built to pass. Both arms ran through headless `claude -p` CLI sessions, each paying a fixed session overhead on top of token cost, so the cost figures are not comparable to real API pricing.";

export type Ratio = {
  /** Median of the per-scenario ratios. */
  median: string;
  low: string;
  high: string;
};

/**
 * The headline. One number, with both of its ranges attached in the same
 * object so no component can render it bare.
 *
 * "~18x" and not a decimal on purpose: the benchmark drives live sites, the
 * run-to-run spread on this figure is about 4%, and a single decimal would
 * imply a precision the measurement does not have. Individual runs have
 * printed 17.6x and 17.8x; neither is the headline.
 */
export const endToEnd = {
  median: "~18x",
  what: "fewer prompt tokens across a 6-turn run",
  /** Spread of the headline figure across repeat runs of the same benchmark. */
  repeatRuns: "16.9x - 18.4x",
  /** Spread across the four scenarios within the reported run. */
  low: "4.6x",
  high: "29.2x",
} as const;

/**
 * Where the ~18x actually comes from. Deliberately four separate rows: the
 * split IS the story, and averaging them into one flattering figure is exactly
 * what this page must not do.
 */
export const mechanisms = [
  {
    key: "compression",
    label: "Compression",
    sub: "grip snapshot vs raw HTML, per turn",
    ratio: { median: "11.3x", low: "2.9x", high: "20.1x" },
    note: "The broad win, and the one the headline is dominated by. Any serious accessibility-tree tool gets some version of it.",
  },
  {
    key: "delta",
    label: "Delta",
    sub: "vs re-sending the full snapshot, per turn",
    ratio: { median: "1.0x", low: "1.0x", high: "8.8x" },
    note: "A median of 1.0x because it only fires on same-document turns, and three of the four scenarios had at most two of six. Deep where it does fire.",
  },
  {
    key: "pruning",
    label: "Pruning",
    sub: "superseded page states dropped, cumulative",
    ratio: { median: "1.5x", low: "1.0x", high: "1.9x" },
    note: "A separate mechanism from the delta. This is what removes the quadratic transcript term on navigation-heavy runs.",
  },
] as const;

/** Numeric mirrors of `mechanisms` for the bar chart, which needs values. */
export const mechanismChartData = [
  { label: "Compression", value: 11.3 },
  { label: "Delta", value: 1.0 },
  { label: "Pruning", value: 1.5 },
  { label: "End to end", value: 18 },
];

export type Scenario = {
  label: string;
  /** How many of the 6 turns stayed on the same document. */
  deltaTurns: number;
  /** Cumulative prompt tokens over the whole run: raw HTML every turn. */
  rawHtml: number;
  /** Cumulative prompt tokens over the whole run: grip, delta + pruning. */
  grip: number;
  /** End-to-end reduction for this scenario. */
  ratio: string;
  /** Largest single prompt in the run. No request ever carries the cumulative. */
  peakRawHtml: number;
  peakGrip: number;
};

/**
 * Ordered by raw-HTML cost, lightest first. Each point is a separate complete
 * 6-turn run, not a moment in time — the chart caption has to say so.
 */
export const scenarios: Scenario[] = [
  { label: "form-fill", deltaTurns: 5, rawHtml: 12_504, grip: 2_711, ratio: "4.6x", peakRawHtml: 3_519, peakGrip: 602 },
  { label: "hackernews", deltaTurns: 1, rawHtml: 293_611, grip: 39_253, ratio: "7.5x", peakRawHtml: 84_454, peakGrip: 7_406 },
  { label: "pythondocs", deltaTurns: 1, rawHtml: 1_038_423, grip: 35_567, ratio: "29.2x", peakRawHtml: 311_129, peakGrip: 8_586 },
  { label: "wikipedia", deltaTurns: 1, rawHtml: 2_648_910, grip: 95_573, ratio: "27.7x", peakRawHtml: 719_034, peakGrip: 21_344 },
];

/**
 * What the delta is worth on the turns where it can fire. Eight of the
 * twenty-four turns in the run were same-document.
 *
 * The low end of the range is a real defect the benchmark caught, not a
 * rounding artefact: when the URL that Target.getTargetInfo reports lags the
 * document, grip diffed two unrelated DOM states and emitted a replacement
 * larger than the snapshot it replaced. Guarded since 5c0e4a5. The range keeps
 * the measured low end because the cited results file records that run.
 */
export const deltaOnSameDocument = {
  median: "9.1x",
  low: "0.5x",
  high: "175x",
  turns: 8,
  totalTurns: 24,
} as const;

export const DELTA_DEFECT =
  "On one turn in this run the delta cost more than the full snapshot it replaced. build_delta decided \"same document\" from a URL that can lag the document; when it lagged, grip diffed two unrelated DOM states and emitted a wholesale replacement. It fired in 6 of 22 runs. Two guards now bound it: a delta that is not meaningfully smaller than the full snapshot loses to it at the point the payload is chosen, and a restamped-document check compares the elements behind shared handles, since a handle stamped per document names a different element after a restart.";

/** Why the delta's median contribution across a mixed run is only 1.0x. */
export const DELTA_CAVEAT =
  "build_delta returns None on a URL change, so on a navigation turn grip sends a full snapshot by design. How often the delta gets to run is a property of the task, not of the compression.";

/**
 * The compression figure is against raw HTML. Against naively tag-stripped
 * text it is far smaller, because most of what grip removes is markup rather
 * than words. Separate, older measurement (evaluation/, 8 pages) and labelled
 * as such — it must travel with the compression claim, never be dropped.
 */
export const strippedTextCaveat = {
  ratio: "~1.4x",
  low: "0.5x",
  high: "3.7x",
  pages: 23,
  source: "evaluation/, the 23 pages where both arms succeeded",
} as const;

/** A 200k context window, and what each approach does to it. */
export const contextWindow = {
  windowTokens: 200_000,
  largestRawHtmlTurn: 373_479,
  largestGripObservation: 27_489,
  note: "Verdicts are keyed on the peak single prompt, not the cumulative: no single request ever carries the cumulative figure. A naive agent that dumps outerHTML cannot put the English Wikipedia article on HTML into a 200k-token context even once, before any history at all.",
} as const;

/** Live headless Chrome, single page, no network fixture. */
export const liveTimings = {
  url: "example.com",
  openSeconds: 0.8,
  snapshotSeconds: 0.01,
} as const;

export const tests = {
  unit: 249,
  gripsearch: 33,
  integration: 74,
} as const;

/**
 * The boundaries. Not marketing softeners: the README, SECURITY.md and the
 * benchmark's own defect log state all of these, and the landing page must not
 * contradict them.
 */
export const limits = [
  {
    title: "Challenges are detected, not defeated",
    body: "grip classifies checkbox, Turnstile, slider, image-grid, text and invisible challenges from the DOM, and attempts checkbox, Turnstile and slider in-process. It reports \"solved\" only when it can verify the outcome. Image-grid and text challenges come back to your model with a screenshot. No third-party solving service, and solve rates are unmeasured.",
  },
  {
    title: "No fingerprint parity",
    body: "grip does not hide that it is automation at the network layer. TLS/JA3 fingerprints and full headless fingerprint parity live below the DevTools Protocol and cannot be reached from a Python client driving stock Chromium. If a site blocks you on IP reputation, that is an egress problem, so route through a proxy.",
  },
  {
    title: "The delta is guarded against costing more than the page it replaces",
    body: "It did not used to be. On a click-driven navigation where the reported URL trailed the document, grip diffed two unrelated pages and emitted 5,701 tokens where the full snapshot was 2,963, in 5 of 16 runs. grip's own benchmark caught it, not a user, and it is now guarded twice: is_worth_sending() makes a delta that is not meaningfully smaller than the full snapshot lose to it, and _is_restamped_document() compares the elements behind shared handles, because a handle stamped per document names a different element once the document restarts. The Hacker News case that motivated it scored 0.04 agreement.",
  },
  {
    title: "Unlabelled inputs cannot be addressed semantically",
    body: "The form-fill scenario addresses inputs by ref (e1, e2) rather than by label, because httpbin's form carries its labels as sibling text and every input reaches the snapshot with an empty label. Refs are what the model sees, so it is a real agent path, but the semantic matcher cannot currently reach an unlabelled input.",
  },
  {
    title: "Narrow on purpose",
    body: "Playwright and Puppeteer are broader automation frameworks with cross-browser support and huge ecosystems. grip does one thing: feed a model the smallest useful view of a page. For human-driven cross-browser E2E testing, use Playwright.",
  },
] as const;
