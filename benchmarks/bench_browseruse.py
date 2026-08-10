"""Observation-payload benchmark: grip vs browser-use.

`bench_competitors.py` measured Playwright MCP and Puppeteer — Node tools with a
much broader scope than grip. It skipped **browser-use**, which is the closest
competitor grip has: Python, CDP-native (it dropped Playwright as the driver in
0.6.0), MIT, and aimed at exactly the same job of handing a page to an LLM.
Publishing a comparison table with that column missing is the omission a reader
is entitled to be suspicious of. This script fills it, on the same pages, with
the same encoder, in the same run as grip's own numbers.

What is measured
----------------
browser-use offers no single "snapshot" call. The page observation it hands the
model each turn is assembled in `AgentMessagePrompt`, so two payloads are
measured and both are reported:

  browseruse_dom    SerializedDOMState.llm_representation(include_attributes=...)
                    — the interactive-element serialisation of the page, the
                    direct counterpart of grip's Summarizer.format(snapshot) and
                    of Playwright MCP's snapshot text. `include_attributes` is
                    AgentSettings().include_attributes, verified equal to
                    DEFAULT_INCLUDE_ATTRIBUTES.
  browseruse_block  AgentMessagePrompt._get_browser_state_description() — the
                    literal <browser_state> block of the user message, i.e. the
                    DOM serialisation plus browser-use's own framing:
                    <page_stats>, the tab list, <page_info>, the
                    [Start of page]/[End of page] markers and the
                    "Interactive elements:" header.

The block is what browser-use actually sends; the DOM serialisation is the
like-for-like comparison. The ratio discussion leads with the DOM one and the
block is reported beside it, because the framing has no grip analogue.

**The 40,000-character cap.** `AgentMessagePrompt` truncates the element text at
`max_clickable_elements_length=40000` characters (its default, and the Agent
default). That cap applies to `browseruse_block` and *not* to
`browseruse_dom`. On a page above the cap the block figure is a truncated
payload, not a compressed one, and rows where it bites are flagged: this script
records the untruncated character count and a `truncated` flag for every page.

**The two payloads do not cover the same thing.** browser-use's serialiser keeps
only nodes inside the viewport plus a 1000px margin
(`DomService.is_element_visible_according_to_all_parents`, viewport_threshold
default 1000); what is below that region survives only as a one-line
`<page_info>… N pages below …</page_info>` hint in the block. grip serialises
the whole document. So a smaller browser-use number can mean "less page", not "denser
encoding", and on a long page the model must spend extra turns scrolling to see
what grip handed it in one. This script records `pages_below` (how many
viewport-heights of the page sit below the serialised region) for every page so
that the size numbers can be read against the coverage they bought.

Screenshots are excluded: `get_browser_state_summary(include_screenshot=False)`.
browser-use runs with vision on by default, so its real per-turn cost is this
text *plus* an image. Text is what grip produces, so text is what is compared,
and the omission is in browser-use's favour.

No LLM is involved anywhere here. `BrowserSession` produces the state without a
model, so no API key is needed and no model output is measured.

Token counting is tiktoken cl100k_base for every column without exception. An
arm that cannot be run produces "unmeasured" plus the error, never a number.

Both browsers are the same Chrome binary — grip's `find_chrome()` result is
passed to browser-use as `executable_path` — so no part of the gap is a
different renderer. They still visit the page at different moments, which is why
the harness is run twice and the variance reported.

Setup (browser-use pulls a large dependency tree and must NOT be installed into
grip's venv):

    python3 -m venv ~/scratch/browseruse/.venv
    ~/scratch/browseruse/.venv/bin/python -m pip install browser-use==0.13.7

Run: .venv/bin/python benchmarks/bench_browseruse.py [--out results.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tiktoken

from grip.browser import Browser
from grip.cdp.launcher import find_chrome
from grip.compression.summarizer import Summarizer
from grip.errors import GripError

ENCODER_NAME = "cl100k_base"
_ENC = tiktoken.get_encoding(ENCODER_NAME)

SCRATCH = Path.home() / "scratch" / "browseruse"
BU_PYTHON = SCRATCH / ".venv" / "bin" / "python"
SETTLE_SECONDS = 1.5
BU_TIMEOUT_SECONDS = 1200

# Same 8 URLs as bench_competitors.py, so the columns line up with
# RESULTS_COMPETITORS.md. See that file's comment for why these are a
# reconstruction rather than the exact set behind README's published figure.
CORPUS: list[tuple[str, str]] = [
    ("wikipedia", "https://en.wikipedia.org/wiki/Python_(programming_language)"),
    ("github", "https://github.com/python/cpython"),
    ("react.dev", "https://react.dev/learn"),
    ("bbc", "https://www.bbc.com/news"),
    ("hacker news", "https://news.ycombinator.com"),
    ("python docs", "https://docs.python.org/3/library/asyncio.html"),
    ("arxiv", "https://arxiv.org/abs/1706.03762"),
    ("example.com", "https://example.com"),
]

ARMS = ["raw_html", "grip", "browseruse_dom", "browseruse_block"]
BU_ARMS = ["browseruse_dom", "browseruse_block"]


def tokens(text: str) -> int:
    return len(_ENC.encode(text, disallowed_special=()))


@dataclass
class PageRow:
    label: str
    url: str
    # arm -> token count, or None when that arm did not produce a payload
    counts: dict[str, int | None] = field(default_factory=dict)
    # arm -> why it produced nothing
    errors: dict[str, str] = field(default_factory=dict)
    # browser-use specifics: untruncated serialisation length and whether the
    # 40,000-character cap fired on the block payload.
    dom_chars: int | None = None
    truncated: bool | None = None
    # how much of the page sits below browser-use's serialised region, in
    # viewport-heights; grip serialises the whole document, browser-use does not
    pages_below: float | None = None
    scroll_hint: bool | None = None
    # first 400 characters of the serialisation, so a failed capture is visible
    # as text rather than inferred from a suspicious number
    sample: str = ""


# --------------------------------------------------------------------------
# grip + raw HTML: measured in-process through grip's own API.
# --------------------------------------------------------------------------

async def capture_grip(rows: dict[str, PageRow]) -> None:
    summarizer = Summarizer()
    async with Browser(headless=True) as browser:
        for label, url in CORPUS:
            row = rows[label]
            try:
                page = await browser.open(url)
                try:
                    await asyncio.sleep(SETTLE_SECONDS)
                    snap = await page.snapshot()
                    raw = await page._page_html()
                    row.counts["grip"] = tokens(summarizer.format(snap))
                    row.counts["raw_html"] = tokens(raw)
                finally:
                    await page.close()
            except (GripError, OSError, TimeoutError, ValueError) as e:
                msg = f"{type(e).__name__}: {e}"
                row.counts["grip"] = None
                row.counts["raw_html"] = None
                row.errors["grip"] = msg
                row.errors["raw_html"] = msg


# --------------------------------------------------------------------------
# browser-use arm: runs in its own interpreter, because its dependency tree must
# not enter grip's venv. The capture script is written out from here so that
# reproducing this needs the venv and this file, nothing else.
# --------------------------------------------------------------------------

CAPTURE_SCRIPT = r'''
"""Written by benchmarks/bench_browseruse.py. Runs in the browser-use venv.

usage: python browseruse_capture.py URLS_JSON OUT_JSON CHROME_EXECUTABLE
"""
import asyncio
import json
import sys

from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.agent.views import AgentSettings
from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.dom.views import DEFAULT_INCLUDE_ATTRIBUTES
from browser_use.filesystem.file_system import FileSystem

from importlib.metadata import version as pkg_version

SETTLE_SECONDS = 1.5
PAGE_TIMEOUT = 120.0
# AgentMessagePrompt's default, and what Agent passes: the element text is cut
# at this many characters inside the <browser_state> block.
MAX_CLICKABLE_ELEMENTS_LENGTH = 40000
EMPTY_MARKERS = (
    "Empty DOM tree",
    "empty page",
)


async def capture_one(session, url, fs, include_attributes):
    await session.navigate_to(url)
    await asyncio.sleep(SETTLE_SECONDS)
    state = await session.get_browser_state_summary(include_screenshot=False)
    dom = state.dom_state.llm_representation(include_attributes=include_attributes)
    prompt = AgentMessagePrompt(
        browser_state_summary=state,
        file_system=fs,
        task="benchmark: observation payload only, no model in the loop",
        include_attributes=include_attributes,
        max_clickable_elements_length=MAX_CLICKABLE_ELEMENTS_LENGTH,
    )
    block = prompt._get_browser_state_description()
    # Coverage: browser-use serialises what is in (or within 1000px of) the
    # viewport, so how much of the page the payload leaves out matters as much
    # as its size. page_info carries the pixels above/below.
    pi = state.page_info
    pages_below = (
        pi.pixels_below / pi.viewport_height
        if pi and pi.viewport_height
        else None
    )
    pages_above = (
        pi.pixels_above / pi.viewport_height
        if pi and pi.viewport_height
        else None
    )
    return {
        "ok": True,
        "url": url,
        "dom": dom,
        "block": block,
        "dom_chars": len(dom),
        "truncated": len(dom) > MAX_CLICKABLE_ELEMENTS_LENGTH,
        "pages_below": pages_below,
        "pages_above": pages_above,
        # scrollable containers whose own contents are partly unserialised
        "scroll_hint": "|scroll element|" in dom,
        "state_error": getattr(state, "state_error", None),
        "empty": any(m in dom for m in EMPTY_MARKERS),
    }


async def main():
    urls = json.loads(open(sys.argv[1]).read())
    out_path = sys.argv[2]
    chrome = sys.argv[3]

    settings = AgentSettings()
    include_attributes = settings.include_attributes
    fs_dir = str((__import__("pathlib").Path(out_path).parent / "bu_fs"))

    try:
        bu_version = pkg_version("browser-use")
    except Exception:
        bu_version = "unknown"

    result = {
        "browser_use_version": bu_version,
        "include_attributes": include_attributes,
        "include_attributes_is_default": include_attributes == DEFAULT_INCLUDE_ATTRIBUTES,
        "max_clickable_elements_length": MAX_CLICKABLE_ELEMENTS_LENGTH,
        "chrome": chrome,
        "rows": [],
        "session_error": None,
    }

    session = BrowserSession(
        browser_profile=BrowserProfile(headless=True, executable_path=chrome)
    )
    try:
        await asyncio.wait_for(session.start(), timeout=180)
    except Exception as e:
        result["session_error"] = "%s: %s" % (type(e).__name__, e)
        open(out_path, "w").write(json.dumps(result))
        return

    fs = FileSystem(base_dir=fs_dir)
    for url in urls:
        try:
            row = await asyncio.wait_for(
                capture_one(session, url, fs, include_attributes),
                timeout=PAGE_TIMEOUT,
            )
        except Exception as e:
            row = {"ok": False, "url": url, "error": "%s: %s" % (type(e).__name__, e)}
        result["rows"].append(row)

    try:
        await asyncio.wait_for(session.kill(), timeout=60)
    except Exception:
        pass
    open(out_path, "w").write(json.dumps(result))


asyncio.run(main())
'''


def _bu_env() -> dict[str, str]:
    env = dict(os.environ)
    # Do not phone home from a benchmark run.
    env["ANONYMIZED_TELEMETRY"] = "false"
    env["BROWSER_USE_CLOUD_SYNC"] = "false"
    return env


def _run_browseruse(urls: list[str], chrome: str) -> tuple[dict | None, str]:
    """Returns (parsed output, error-string). Exactly one is meaningful."""
    if not BU_PYTHON.exists():
        return None, (
            f"missing {BU_PYTHON}; create it with "
            f"`python3 -m venv {SCRATCH / '.venv'} && "
            f"{BU_PYTHON} -m pip install browser-use==0.13.7`"
        )
    SCRATCH.mkdir(parents=True, exist_ok=True)
    script = SCRATCH / "browseruse_capture.py"
    script.write_text(CAPTURE_SCRIPT)
    with tempfile.TemporaryDirectory() as tmp:
        urls_path = Path(tmp) / "urls.json"
        out_path = Path(tmp) / "out.json"
        urls_path.write_text(json.dumps(urls))
        try:
            proc = subprocess.run(
                [str(BU_PYTHON), str(script), str(urls_path), str(out_path), chrome],
                cwd=SCRATCH,
                capture_output=True,
                text=True,
                env=_bu_env(),
                timeout=BU_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return None, f"browseruse_capture.py exceeded {BU_TIMEOUT_SECONDS}s"
        if not out_path.exists():
            return None, (
                f"browseruse_capture.py exited {proc.returncode}: "
                f"{proc.stderr.strip()[-800:]}"
            )
        return json.loads(out_path.read_text()), ""


def capture_browseruse(rows: dict[str, PageRow], chrome: str) -> dict[str, object]:
    data, err = _run_browseruse([u for _, u in CORPUS], chrome)
    meta: dict[str, object] = {"error": err, "chrome": chrome}
    if data is None:
        for row in rows.values():
            for arm in BU_ARMS:
                row.counts[arm] = None
                row.errors[arm] = err
        return meta

    meta.update(
        {
            "version": data.get("browser_use_version"),
            "include_attributes_is_default": data.get("include_attributes_is_default"),
            "include_attributes_count": len(data.get("include_attributes") or []),
            "max_clickable_elements_length": data.get("max_clickable_elements_length"),
            "session_error": data.get("session_error"),
        }
    )
    by_url = {r["url"]: r for r in data.get("rows", [])}
    for label, url in CORPUS:
        row = rows[label]
        r = by_url.get(url)
        if r is None or not r.get("ok"):
            reason = (
                (r or {}).get("error") or data.get("session_error") or "no result row"
            )
            for arm in BU_ARMS:
                row.counts[arm] = None
                row.errors[arm] = reason
            continue
        # A payload that is browser-use's own empty-state text is not a payload.
        if r.get("empty"):
            reason = f"empty DOM serialisation: {r['dom'][:120]!r}"
            for arm in BU_ARMS:
                row.counts[arm] = None
                row.errors[arm] = reason
            row.sample = r["dom"][:400]
            continue
        row.counts["browseruse_dom"] = tokens(r["dom"])
        row.counts["browseruse_block"] = tokens(r["block"])
        row.dom_chars = r["dom_chars"]
        row.truncated = r["truncated"]
        row.pages_below = r.get("pages_below")
        row.scroll_hint = r.get("scroll_hint")
        row.sample = r["dom"][:400]
        if r.get("state_error"):
            row.errors["browseruse_state_error"] = str(r["state_error"])
    return meta


# --------------------------------------------------------------------------
# Reporting.
# --------------------------------------------------------------------------

def _versions(meta: dict[str, object]) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        from grip import __version__ as grip_version
        out["grip"] = grip_version
    except ImportError:
        out["grip"] = "unknown"
    out["browser-use"] = str(meta.get("version") or "unmeasured")
    out["tiktoken"] = getattr(tiktoken, "__version__", "unknown")
    out["python (grip)"] = sys.version.split()[0]
    if BU_PYTHON.exists():
        try:
            out["python (browser-use)"] = subprocess.run(
                [str(BU_PYTHON), "-c", "import sys;print(sys.version.split()[0])"],
                capture_output=True, text=True, timeout=60,
            ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            out["python (browser-use)"] = "unknown"
    out["chrome"] = str(meta.get("chrome") or "unknown")
    return out


def _cell(v: int | None) -> str:
    return f"{v:,}" if v is not None else "unmeasured"


def _ratio_stats(rows: list[PageRow], arm: str) -> dict[str, object]:
    """Both statistics, named. The conservative one is median_of_ratios."""
    pairs = [
        (r.counts.get("grip"), r.counts.get(arm))
        for r in rows
        if r.counts.get("grip") and r.counts.get(arm)
    ]
    if not pairs:
        return {"n": 0}
    ratios = [other / grip for grip, other in pairs]
    grip_median = statistics.median([g for g, _ in pairs])
    other_median = statistics.median([o for _, o in pairs])
    return {
        "n": len(pairs),
        "median_of_ratios": statistics.median(ratios),
        "ratio_of_medians": other_median / grip_median,
        "min_ratio": min(ratios),
        "max_ratio": max(ratios),
        "grip_loses_on": [
            r.label
            for r in rows
            if r.counts.get("grip")
            and r.counts.get(arm)
            and r.counts[arm] <= r.counts["grip"]
        ],
    }


def report(rows: list[PageRow], meta: dict[str, object], elapsed: float) -> None:
    print(f"\nencoder: tiktoken {ENCODER_NAME}")
    print("versions: " + ", ".join(f"{k}={v}" for k, v in _versions(meta).items()))
    print(
        "browser-use include_attributes is the library default: "
        f"{meta.get('include_attributes_is_default')} "
        f"({meta.get('include_attributes_count')} attributes)"
    )
    print(
        "block truncation cap: "
        f"{meta.get('max_clickable_elements_length')} characters"
    )

    header = ["page", *ARMS, "bu dom chars", "bu truncated", "bu pages below"]
    print("\n| " + " | ".join(header) + " |")
    print("|" + "|".join(["---"] * len(header)) + "|")
    for row in rows:
        cells = [
            row.label,
            *(_cell(row.counts.get(a)) for a in ARMS),
            f"{row.dom_chars:,}" if row.dom_chars is not None else "-",
            "yes" if row.truncated else ("no" if row.truncated is not None else "-"),
            f"{row.pages_below:.1f}" if row.pages_below is not None else "-",
        ]
        print("| " + " | ".join(cells) + " |")

    print("\nmedian (pages where that arm produced a payload):")
    for arm in ARMS:
        vals = [r.counts.get(arm) for r in rows]
        vals = [v for v in vals if v is not None]
        if not vals:
            print(f"  {arm:17s} unmeasured (0/{len(rows)} pages)")
            continue
        print(
            f"  {arm:17s} {statistics.median(vals):>10,.0f}   "
            f"range {min(vals):,} to {max(vals):,}   n={len(vals)}/{len(rows)}"
        )

    # Ratios are browser-use / grip: above 1.00 means grip's payload is smaller.
    # Which of the two statistics flatters grip is not fixed — on these pages
    # they disagree in direction on the block column — so the smaller of the two
    # is marked rather than assumed.
    print("\ngrip vs browser-use (ratio = browser-use / grip; >1 means grip is smaller):")
    for arm in BU_ARMS:
        s = _ratio_stats(rows, arm)
        if not s.get("n"):
            print(f"  {arm}: unmeasured")
            continue
        mor, rom = s["median_of_ratios"], s["ratio_of_medians"]
        worse = "median-of-ratios" if mor <= rom else "ratio-of-medians"
        print(
            f"  {arm}: median of per-page ratios {mor:.2f}x | "
            f"ratio of medians {rom:.2f}x | "
            f"less flattering to grip: {worse} | "
            f"range {s['min_ratio']:.2f}x-{s['max_ratio']:.2f}x | n={s['n']}"
        )
        if s["grip_loses_on"]:
            print(f"    browser-use is smaller or equal on: {s['grip_loses_on']}")

    print("\nfirst 200 chars of each browser-use serialisation (look at the text):")
    for row in rows:
        text = row.sample.replace("\n", "\\n")[:200] or "(none)"
        print(f"  {row.label:12s} {text}")

    failures = [(r.label, a, m) for r in rows for a, m in r.errors.items()]
    if failures:
        print("\nunmeasured cells / state errors:")
        for label, arm, msg in failures:
            print(f"  {label} / {arm}: {msg}")

    print(f"\ntotal wall time: {elapsed:.1f}s")


async def run() -> dict[str, object]:
    t0 = time.monotonic()
    rows = {label: PageRow(label=label, url=url) for label, url in CORPUS}

    chrome = find_chrome() or ""
    await capture_grip(rows)
    meta = capture_browseruse(rows, chrome)

    ordered = [rows[label] for label, _ in CORPUS]
    report(ordered, meta, time.monotonic() - t0)
    return {
        "encoder": ENCODER_NAME,
        "versions": _versions(meta),
        "browser_use": meta,
        "ratios": {arm: _ratio_stats(ordered, arm) for arm in BU_ARMS},
        "rows": [asdict(r) for r in ordered],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="write raw counts as JSON to this path")
    args = parser.parse_args()

    payload = asyncio.run(run())
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
