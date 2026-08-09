"""Does grip's stealth flag reduce or increase detectability?

BetterWright measured the equivalent JS-shim approach against live reCAPTCHA and
found it made detection EASIER (their cloak-v2.ts:16-18: "Page-world shims are
intentionally avoided: live reCAPTCHA verification showed that the old init pack
made Cloak easier, not harder, to detect"). grip ships two flags with the same
shape — `--disable-blink-features=AutomationControlled` and a hardcoded UA — so
the same question applies here and guessing is not an answer. This script counts
automation tells in both modes.

Probes are chosen because they *report signals* rather than a pass/fail verdict,
so the output is a count and not a coin flip.

RESULT: UNMEASURED as of 2026-08-10.
-----------------------------------
NO numbers are recorded below. Chrome in the development sandbox cannot load any
http(s) document. That was proven with grip out of the picture: a raw
`chrome --dump-dom` against a LOCAL http server times out while the server's
access log stays empty, whereas `data:` URLs navigate in 0.03s and `file://`
works.

Running this script here on 2026-08-10 produced, as expected:

    https://bot.sannysoft.com/                stealth=False  ERROR: TimeoutError
    https://bot.sannysoft.com/                stealth=True   ERROR: TimeoutError
    https://abrahamjuliot.github.io/creepjs/  stealth=False  ERROR: TimeoutError
    https://abrahamjuliot.github.io/creepjs/  stealth=True   ERROR: TimeoutError
    4 of 4 runs were unusable  (exit 1)

Those are network artefacts, not detection results. Had the script scored them
as zero tells in both modes it would have read as "no difference", which is why
an unrendered probe is reported as unusable and exits non-zero.

To measure, run on a host with outbound network:

    .venv/bin/python -m evaluation.stealth_measurement

Then record the counts in this docstring, dated, and act on them:
  - more tells with stealth=True  -> deprecate the flag, keep the UA override
                                     only where a caller sets it explicitly
  - fewer tells with stealth=True -> keep it, document the measured delta, keep
                                     the "not a full evasion suite" caveat
  - difference within noise       -> say so; do not ship a flag whose value is
                                     unmeasured

Until then README must describe `stealth=` as unmeasured. An unmeasured flag
documented as beneficial is exactly the kind of claim this project's audit
already caught once.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys

from grip.browser import Browser
from grip.errors.types import GripError

PROBES = [
    "https://bot.sannysoft.com/",
    "https://abrahamjuliot.github.io/creepjs/",
]

# Markers each probe writes when a check fails. Counting markers, rather than
# reading a verdict, keeps the output ordinal: two runs can be compared even
# when neither is a clean pass.
FAILURE_MARKERS = re.compile(
    r"\b(failed|present \(failed\)|missing \(failed\)|detected|automation|"
    r"headlesschrome|webdriver)\b",
    re.IGNORECASE,
)

# A probe that never rendered scores zero tells, which is indistinguishable from
# a perfect pass. Below this much text the run is reported as unusable instead.
MIN_USABLE_CHARS = 400


async def probe(url: str, stealth: bool, timeout: float) -> tuple[int, int]:
    """Return (tell_count, text_length) for one probe in one mode."""
    async with Browser(headless=True, stealth=stealth) as browser:
        async with asyncio.timeout(timeout):
            page = await browser.open(url)
            # The fingerprint probes score asynchronously after load; reading the
            # DOM immediately would undercount both arms.
            await asyncio.sleep(6.0)
            snap = await page.snapshot()
        text = snap.text_content or ""
        return len(FAILURE_MARKERS.findall(text)), len(text)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()

    rows: list[tuple[str, str, str]] = []
    unusable = 0

    for url in PROBES:
        for label, stealth in (("stealth=False", False), ("stealth=True", True)):
            try:
                tells, length = await probe(url, stealth, args.timeout)
            # A launch failure, a dead proxy and a timeout are all "no data", and
            # every one of them must stay distinct from "zero tells".
            except (OSError, TimeoutError, RuntimeError, GripError) as exc:
                rows.append((url, label, f"ERROR: {type(exc).__name__}: {exc}"))
                unusable += 1
                continue
            if length < MIN_USABLE_CHARS:
                rows.append((url, label, f"UNUSABLE (rendered {length} chars)"))
                unusable += 1
            else:
                rows.append((url, label, f"{tells} tells ({length} chars)"))

    width = max(len(u) for u in PROBES)
    print(f"{'probe'.ljust(width)}  {'mode'.ljust(13)}  result")
    for url, label, result in rows:
        print(f"{url.ljust(width)}  {label.ljust(13)}  {result}")

    if unusable:
        print(
            f"\n{unusable} of {len(rows)} runs were unusable. A run that did not "
            "render is NOT a zero-tell result — do not record these as a "
            "measurement.",
            file=sys.stderr,
        )
        return 1
    print("\nRecord these counts in this module's docstring, dated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
