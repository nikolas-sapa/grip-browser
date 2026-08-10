"""Reach evaluation: can a static HTTP fetch see what a rendered browser sees?

Method
------
For each URL, both arms fetch the *same* page. The only variable is the fetch
mechanism, so nothing about ranking, discovery or vendor pricing confounds the result.

  browser arm  — grip: real Chrome, JS executed, `page.read()` extracts main content
  static arm   — plain HTTP GET, tags stripped. This is what a static-fetch retrieval
                 vendor's extractor has to work with.

Scoring avoids the obvious trap. Hand-written questions would let the author pick
examples that flatter the browser. Instead the marker is chosen by a **fixed rule**:
the longest content block the browser recovered. If static fetch also recovers the
page's substance, that block's text will be present in its output too.

A page only counts if the browser arm recovered something in the first place — a URL
neither arm can read tells us nothing about rendering and is reported separately.

Run: .venv/bin/python -m evaluation.run_reach
"""
from __future__ import annotations

import asyncio
import contextlib
import gzip
import html as html_mod
import json
import re
import sys
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

from evaluation.corpus import CORPUS
from grip.browser import Browser

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

_SCRIPT_STYLE = re.compile(
    r"<(script|style|noscript|template)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# Marker length: long enough that an accidental match is implausible, short enough
# that trivial reformatting between the two arms does not break a real match.
MARKER_WORDS = 12
MIN_BLOCK_WORDS = 15


@dataclass
class Row:
    category: str
    url: str
    browser_ok: bool
    static_ok: bool
    browser_chars: int
    static_chars: int
    static_status: int | str
    marker: str
    note: str = ""


def normalise(text: str) -> str:
    """Reduce to lowercase alphanumerics with **all** whitespace removed.

    Whitespace cannot be trusted here: stripping tags inserts a space at every tag
    boundary, so `<code>foo</code>bar` reads as "foo bar" statically but "foobar"
    through innerText. An earlier version of this scorer collapsed whitespace instead
    of deleting it, and consequently scored pages as browser-only wins when static
    fetch had in fact retrieved *more* text than the browser. Deleting whitespace
    removes the artefact entirely."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def static_fetch(url: str, timeout: float = 20.0) -> tuple[str, int | str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            enc = (resp.headers.get("Content-Encoding") or "").lower()
            status = resp.status
    except urllib.error.HTTPError as e:
        return "", e.code
    except Exception as e:
        return "", type(e).__name__

    if enc == "gzip":
        # A mislabelled encoding is not fatal — keep the bytes as they came.
        with contextlib.suppress(Exception):
            raw = gzip.decompress(raw)
    elif enc == "deflate":
        with contextlib.suppress(Exception):
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)

    html = raw.decode("utf-8", errors="replace")
    text = _SCRIPT_STYLE.sub(" ", html)
    text = _TAG.sub(" ", text)
    # Entities must be decoded before comparison. The browser sees "->" where the
    # source says "-&gt;", and normalise() would otherwise fold that stray "gt" into
    # the text as letters — a second artefact that scored real static successes as
    # browser-only wins.
    text = html_mod.unescape(text)
    return _WS.sub(" ", text).strip(), status


def pick_marker(blocks) -> str:
    """Fixed rule, applied identically to every page: the longest content block the
    browser recovered. Not chosen by hand, so it cannot be chosen to flatter."""
    candidates = [
        b for b in blocks
        if b.kind != "heading" and len(b.text.split()) >= MIN_BLOCK_WORDS
    ]
    if not candidates:
        return ""
    longest = max(candidates, key=lambda b: len(b.text))
    return " ".join(longest.text.split()[:MARKER_WORDS])


async def main() -> None:
    rows: list[Row] = []
    async with Browser(headless=True, stealth=True) as browser:
        for category, url in CORPUS:
            page = None
            b_chars, marker, note = 0, "", ""
            try:
                page = await asyncio.wait_for(browser.open(url), timeout=30)
                snap = await page.snapshot()
                if snap.page_error is not None:
                    note = f"browser blocked: {snap.page_error.type.value}"
                doc = await page.read()
                b_chars = len(doc.text)
                marker = pick_marker(doc.blocks)
            except Exception as e:
                note = f"browser error: {type(e).__name__}"
            finally:
                if page is not None:
                    # Teardown: nothing useful to report if closing fails.
                    with contextlib.suppress(Exception):
                        await page.close()

            static_text, status = static_fetch(url)
            browser_ok = bool(marker)
            static_ok = bool(marker) and normalise(marker) in normalise(static_text)

            rows.append(Row(
                category=category, url=url,
                browser_ok=browser_ok, static_ok=static_ok,
                browser_chars=b_chars, static_chars=len(static_text),
                static_status=status, marker=marker[:70], note=note,
            ))
            print(
                f"{'OK ' if browser_ok else '-- '}browser  "
                f"{'OK ' if static_ok else '-- '}static  "
                f"[{category:9}] {url[:64]}",
                flush=True,
            )
            await asyncio.sleep(0.5)

    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": [asdict(r) for r in rows],
    }
    # ASYNC230: a single blocking write after all fetching is done, not in a hot path.
    with Path("evaluation/results.json").open("w") as f:  # noqa: ASYNC230
        json.dump(out, f, indent=1)

    report(rows)


def report(rows: list[Row]) -> None:
    usable = [r for r in rows if r.browser_ok]
    unreadable = [r for r in rows if not r.browser_ok]

    print("\n" + "=" * 72)
    print(f"Pages where the browser recovered content: {len(usable)}/{len(rows)}")
    print(f"  of those, static fetch also recovered it: "
          f"{sum(r.static_ok for r in usable)}/{len(usable)}")

    print(f"\n{'category':11}{'n':>4}{'browser':>10}{'static':>9}{'gap':>7}")
    for cat in ("static", "spa", "hybrid", "protected"):
        group = [r for r in rows if r.category == cat]
        if not group:
            continue
        b = sum(r.browser_ok for r in group)
        s = sum(r.static_ok for r in group)
        print(f"{cat:11}{len(group):>4}{b:>10}{s:>9}{b - s:>7}")

    tot_b = sum(r.browser_ok for r in rows)
    tot_s = sum(r.static_ok for r in rows)
    print(f"{'TOTAL':11}{len(rows):>4}{tot_b:>10}{tot_s:>9}{tot_b - tot_s:>7}")

    if unreadable:
        print("\nNeither arm could read these — reported, not hidden:")
        for r in unreadable:
            print(f"  {r.url[:60]:62} {r.note or r.static_status}")

    wins = [r for r in usable if not r.static_ok]
    if wins:
        print("\nBrowser recovered content static fetch did not:")
        for r in wins:
            print(f"  [{r.category:9}] {r.url[:58]:60} "
                  f"browser {r.browser_chars:>7,} vs static {r.static_chars:>7,} chars")

    losses = [r for r in rows if r.static_ok and not r.browser_ok]
    if losses:
        print("\nStatic fetch won where the browser failed:")
        for r in losses:
            print(f"  {r.url}")

    # Second axis. If both arms recover the substance, the question is no longer
    # *whether* you get the content but how much boilerplate rides along with it —
    # which is what the model is billed for.
    both = [r for r in usable if r.static_ok and r.browser_chars]
    if both:
        ratios = sorted(r.static_chars / r.browser_chars for r in both)
        mid = ratios[len(ratios) // 2]
        print(f"\nExtraction overhead, {len(both)} pages where both arms succeeded:")
        print(f"  static fetch returns a median {mid:.1f}x the characters the browser "
              f"does\n  for the same substance (range {ratios[0]:.1f}x-{ratios[-1]:.1f}x).")
        print("  The excess is navigation, footers and inline script residue — text a "
              "model\n  pays for and cannot use.")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
