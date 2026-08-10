"""Cross-tool observation-payload benchmark: grip vs Playwright MCP vs Puppeteer.

grip's README compares itself to Playwright MCP and Puppeteer with "not measured"
in both competitor columns. A table where only your own column has a number is
advocacy, not evidence. This script fills the other columns on the same pages
with the same encoder.

What is measured
----------------
For one page, the payload each tool would put in a model's context as its primary
page observation:

  grip              Summarizer.format(snapshot)
  playwright_mcp    the tools/call result text of @playwright/mcp's snapshot tool,
                    obtained over real stdio MCP (initialize / tools/list /
                    tools/call), preamble included
  puppeteer_html    page.content()
  puppeteer_a11y    JSON.stringify(page.accessibility.snapshot()) — compact, no
                    indent; the serialisation is a choice and it moves the number
  raw_html          document.documentElement.outerHTML via grip's own CDP path,
                    the baseline all four are compressing against

Token counting is tiktoken cl100k_base for every column without exception. No
column is estimated, extrapolated or copied from documentation: a tool that
cannot be run produces "unmeasured" plus the error, never a number.

Each arm drives its own browser, because that is how someone would actually use
it. The three browsers therefore see the page at three slightly different
moments; live pages differ run to run, which is why the harness is run twice and
the variance reported.

Run: .venv/bin/python benchmarks/bench_competitors.py [--out results.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tiktoken

from grip.browser import Browser
from grip.compression.summarizer import Summarizer
from grip.errors import GripError

ENCODER_NAME = "cl100k_base"
_ENC = tiktoken.get_encoding(ENCODER_NAME)

SCRATCH = Path.home() / "scratch" / "competitors"
SETTLE_SECONDS = 1.5
NODE_TIMEOUT_SECONDS = 900

# --------------------------------------------------------------------------
# Corpus.
#
# The script behind README's "median 77,588 raw / 2,018 grip across 8 real
# pages" is NOT in the tree — docs/research/proxy-pricing.md:372 says so
# explicitly about the same missing benchmark. So the exact URLs cannot be
# reused verbatim. These eight are RECONSTRUCTED from the site names README:27
# lists, choosing the specific path this repo already uses for that site
# elsewhere (evaluation/corpus.py, evaluation/page_weight_corpus.py,
# docs/research/proxy-pricing.md) wherever one exists.
#
# Consequence, stated loudly in RESULTS_COMPETITORS.md: grip's column here is
# re-measured from scratch on these URLs. It is not the published 2,018 and
# should not be read as reproducing it.
# --------------------------------------------------------------------------

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

ARMS = ["raw_html", "grip", "playwright_mcp", "puppeteer_html", "puppeteer_a11y"]


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
# Node arms: each script drives its own browser and writes raw payloads to JSON.
# --------------------------------------------------------------------------

def _run_node(script: str, urls: list[str]) -> tuple[dict | list | None, str]:
    """Returns (parsed output, error-string). Exactly one is meaningful."""
    path = SCRATCH / script
    if not path.exists():
        return None, f"missing {path}; run npm install in {SCRATCH}"
    with tempfile.TemporaryDirectory() as tmp:
        urls_path = Path(tmp) / "urls.json"
        out_path = Path(tmp) / "out.json"
        urls_path.write_text(json.dumps(urls))
        try:
            proc = subprocess.run(
                ["node", str(path), str(urls_path), str(out_path)],
                cwd=SCRATCH,
                capture_output=True,
                text=True,
                timeout=NODE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return None, f"{script} exceeded {NODE_TIMEOUT_SECONDS}s"
        if proc.returncode != 0 or not out_path.exists():
            return None, f"{script} exited {proc.returncode}: {proc.stderr.strip()[-800:]}"
        return json.loads(out_path.read_text()), ""


def capture_puppeteer(rows: dict[str, PageRow]) -> None:
    data, err = _run_node("puppeteer_capture.js", [u for _, u in CORPUS])
    if data is None:
        for row in rows.values():
            for arm in ("puppeteer_html", "puppeteer_a11y"):
                row.counts[arm] = None
                row.errors[arm] = err
        return
    by_url = {r["url"]: r for r in data}
    for label, url in CORPUS:
        row = rows[label]
        r = by_url.get(url)
        if r is None or not r["ok"]:
            reason = (r or {}).get("error") or "no result row"
            for arm in ("puppeteer_html", "puppeteer_a11y"):
                row.counts[arm] = None
                row.errors[arm] = reason
            continue
        row.counts["puppeteer_html"] = tokens(r["content_html"])
        row.counts["puppeteer_a11y"] = tokens(r["a11y_json"])


def capture_playwright_mcp(rows: dict[str, PageRow]) -> dict[str, object]:
    data, err = _run_node("playwright_mcp_capture.js", [u for _, u in CORPUS])
    meta: dict[str, object] = {"tools": [], "tool_used": None, "error": err}
    if data is None:
        for row in rows.values():
            row.counts["playwright_mcp"] = None
            row.errors["playwright_mcp"] = err
        return meta
    meta["tools"] = data.get("tools", [])
    if data.get("server_error"):
        meta["error"] = str(data["server_error"])
    by_url = {r["url"]: r for r in data.get("rows", [])}
    for label, url in CORPUS:
        row = rows[label]
        r = by_url.get(url)
        if r is None or not r["ok"]:
            row.counts["playwright_mcp"] = None
            row.errors["playwright_mcp"] = (
                (r or {}).get("error") or data.get("server_error") or "no result row"
            )
            continue
        row.counts["playwright_mcp"] = tokens(r["payload"])
        meta["tool_used"] = r["tool"]
    return meta


# --------------------------------------------------------------------------
# Reporting.
# --------------------------------------------------------------------------

def _versions() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        proc = subprocess.run(
            ["npm", "ls", "--depth", "0", "--json"],
            cwd=SCRATCH, capture_output=True, text=True, timeout=120,
        )
        deps = json.loads(proc.stdout or "{}").get("dependencies", {})
        for name, info in deps.items():
            out[name] = str(info.get("version", "unknown"))
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        out["npm ls"] = f"failed: {type(e).__name__}: {e}"
    try:
        from grip import __version__ as grip_version
        out["grip"] = grip_version
    except ImportError:
        out["grip"] = "unknown"
    out["tiktoken"] = getattr(tiktoken, "__version__", "unknown")
    out["python"] = sys.version.split()[0]
    try:
        out["node"] = subprocess.run(
            ["node", "-v"], capture_output=True, text=True, timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        out["node"] = "unknown"
    return out


def _cell(v: int | None) -> str:
    return f"{v:,}" if v is not None else "unmeasured"


def report(rows: list[PageRow], meta: dict[str, object], elapsed: float) -> None:
    print(f"\nencoder: tiktoken {ENCODER_NAME}")
    print("versions: " + ", ".join(f"{k}={v}" for k, v in _versions().items()))
    print(f"playwright-mcp tools/list: {meta.get('tools')}")
    print(f"playwright-mcp tool counted: {meta.get('tool_used')}")

    header = ["page", *ARMS]
    print("\n| " + " | ".join(header) + " |")
    print("|" + "|".join(["---"] * len(header)) + "|")
    for row in rows:
        cells = [row.label, *(_cell(row.counts.get(a)) for a in ARMS)]
        print("| " + " | ".join(cells) + " |")

    print("\nmedian (pages where that arm produced a payload):")
    for arm in ARMS:
        vals = [r.counts.get(arm) for r in rows]
        vals = [v for v in vals if v is not None]
        if not vals:
            print(f"  {arm:16s} unmeasured (0/{len(rows)} pages)")
            continue
        print(
            f"  {arm:16s} {statistics.median(vals):>10,.0f}   "
            f"range {min(vals):,} to {max(vals):,}   n={len(vals)}/{len(rows)}"
        )

    failures = [(r.label, a, m) for r in rows for a, m in r.errors.items()]
    if failures:
        print("\nunmeasured cells:")
        for label, arm, msg in failures:
            print(f"  {label} / {arm}: {msg}")

    print(f"\ntotal wall time: {elapsed:.1f}s")


async def run() -> dict[str, object]:
    t0 = time.monotonic()
    rows = {label: PageRow(label=label, url=url) for label, url in CORPUS}

    await capture_grip(rows)
    capture_puppeteer(rows)
    meta = capture_playwright_mcp(rows)

    ordered = [rows[label] for label, _ in CORPUS]
    report(ordered, meta, time.monotonic() - t0)
    return {
        "encoder": ENCODER_NAME,
        "versions": _versions(),
        "playwright_mcp": meta,
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
