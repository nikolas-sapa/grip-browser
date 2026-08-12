"""Per-signal stealth measurement against https://bot.sannysoft.com/.

Unlike evaluation/stealth_measurement.py (which counts regex "tell" hits in
flattened page text), this reads the probe's own result table directly out of
the DOM — `table tr` rows, `cells[0]` = signal name, `cells[1]` = its verdict
cell (text + CSS class) — so failures are attributable to a specific signal,
not just a count. Precedent for raw-CDP-in-benchmarks: bench_grip.py already
imports JS constants and evaluates them directly rather than going through the
Page snapshot pipeline.

RESULT: measured 2026-08-12, single run.
------------------------------------------
    chrome: Chrome for Testing 151.0.7922.34, macOS arm64 (Apple M3),
            --headless=new, ANGLE Metal renderer (not SwiftShader)
    probe:  https://bot.sannysoft.com/, 57 signal rows

    signal                    stealth=False           stealth=True
    User Agent                HeadlessChrome/151 FAIL Chrome/151 pass
    WebDriver                 present (FAIL)          missing (pass)
    HEADCHR_UA                FAIL                     ok (pass)
    CHR_MEMORY                FAIL                     ok (pass)
    navigator.userAgent       HeadlessChrome/151 FAIL Chrome/151 pass
    (52 other rows)           pass                     pass
    ---
    total FAIL rows           5 / 57                   0 / 57

Raw before/after row lists: benchmarks/corpus/results/stealth_signals_20260812.json

All five rows flipped from FAIL to pass under the same change (the UA
override / navigator.webdriver removal — grip/browser.py's
Browser._resolve_stealth_ua, applied via Network.setUserAgentOverride, plus
--disable-blink-features=AutomationControlled). For User Agent,
navigator.userAgent, HEADCHR_UA, and WebDriver the row's own text names the
mechanism directly (UA string / navigator.webdriver). CHR_MEMORY's row does
not name what it checks — it was observed to flip along with the others, not
traced to a specific navigator.deviceMemory/performance.memory read, so this
does not claim to know why. On THIS Chrome build, flipping those two tells
was already enough to reach 0/57.

What this does NOT show, measured separately (all on the same run/build):
  - WebGL Vendor/Renderer already report the real ANGLE/Apple GPU here, not
    SwiftShader — nothing to fix on this host. A GPU-less Linux CI/Docker host
    would likely report SwiftShader instead; that was NOT measured and is not
    claimed either way.
  - navigator.plugins/mimeTypes, navigator.languages, permissions.query vs.
    Notification.permission, window.chrome, screen/outerWidth were all
    already consistent before any change here — see the "5/57" count above,
    not a longer list. Notifications/geolocation permission consistency in
    particular is closed by grip's existing default-deny (_DEFAULT_PERMISSIONS
    in browser.py), unrelated to stealth=.
  - navigator.userAgentData becomes `undefined` under ANY UA string override
    on this Chrome build (with or without the old hardcoded UA, with or
    without this fix) — Chromium only preserves it when an explicit
    userAgentMetadata payload accompanies Network.setUserAgentOverride, and
    that payload's GREASE'd brand entry can only be read from an
    already-loaded real page, which is exactly what stealth mode intercepts
    before. Spoofing it by hand risks a *worse*, fabricated tell (a wrong or
    static brand list) than leaving it undefined. Left unfixed, documented.
  - The outgoing `User-Agent` request header, not just navigator.userAgent —
    verified separately against a local echo server
    (tests/integration/test_concurrent_pages.py::
    test_stealth_ua_changes_the_outgoing_header_not_just_navigator_ua): the
    header matches the JS-visible value in both modes, so there is no
    JS-vs-header cross-check inconsistency for this build.
  - Popup coverage: the UA override is per-CDP-target, unlike the old launch
    flag (browser-wide). A popup window.open() opens under
    NavigationPolicy(allow_popups=True) gets its own target with independent
    Network-domain state — Page._resume_popup_target (grip/page.py)
    re-applies the same stealth UA to the popup's session before releasing
    it, verified by unit test against a mocked engine
    (tests/unit/test_page.py::test_stealth_ua_applied_to_popup_session_before_resume).
    Not verified against a real popup: real-Chrome popup attach is a
    pre-existing, already-documented gap unrelated to this change (see the
    skip reason on test_wait_for_popup_observes_a_real_popup in
    tests/integration/test_capabilities.py) — Target.attachedToTarget was
    never observed to fire for a window.open() popup on this Chrome/CDP
    version at all, so this code path could not be exercised end to end here.
  - creepjs (abrahamjuliot.github.io/creepjs), coarse marker count only:
    3 tells -> 1 tell (re-measured 2026-08-12; was 3 -> 0 on 2026-08-10 — see
    evaluation/stealth_measurement.py's docstring for that run-to-run
    variance, itself evidence for the next line).
  - Not tested against any live anti-bot system, not repeated beyond the two
    dated runs above, silent on TLS/JA3 (grip drives real Chromium; that
    fingerprint was never a gap CDP could reach or fail to reach — see README).

To re-measure:
    .venv/bin/python benchmarks/bench_stealth_signals.py --save-json <path>
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from grip.browser import Browser
from grip.cdp.launcher import find_chrome

PROBE_URL = "https://bot.sannysoft.com/"

# sannysoft renders its result table asynchronously (some rows populate after
# a WebGL/plugin probe resolves) — poll until the row count stops growing
# instead of a fixed sleep, so a slow probe never gets undercounted and a fast
# one never costs more than it has to.
_POLL_INTERVAL_S = 0.5
_STABLE_POLLS_REQUIRED = 3

_EXTRACT_TABLE_JS = """
(function () {
  const rows = [];
  for (const tr of document.querySelectorAll('table tr')) {
    const cells = tr.querySelectorAll('td');
    if (cells.length < 2) continue;
    const name = (cells[0].innerText || '').trim();
    if (!name) continue;
    const valueCell = cells[1];
    rows.push({
      name: name,
      value: (valueCell.innerText || '').trim(),
      cls: valueCell.className || ''
    });
  }
  return JSON.stringify(rows);
})();
"""


async def _wait_for_stable_table(page: object, timeout: float) -> list[dict[str, str]]:
    import time

    deadline = time.monotonic() + timeout
    last_count = -1
    stable_polls = 0
    rows: list[dict[str, str]] = []
    while time.monotonic() < deadline:
        raw = await page._eval(_EXTRACT_TABLE_JS)  # type: ignore[attr-defined]
        rows = json.loads(raw) if raw else []
        if len(rows) == last_count and len(rows) > 0:
            stable_polls += 1
            if stable_polls >= _STABLE_POLLS_REQUIRED:
                return rows
        else:
            stable_polls = 0
        last_count = len(rows)
        await asyncio.sleep(_POLL_INTERVAL_S)
    return rows


# A row's own CSS class is sannysoft's verdict, not a regex guess against its
# text — "failed" is the literal class it applies to a detected-as-headless
# signal. Falls back to text markers only for rows that carry no such class
# (a handful of informational, not pass/fail, rows).
def _is_failed(row: dict[str, str]) -> bool:
    cls = row.get("cls", "").lower()
    if "failed" in cls:
        return True
    if "passed" in cls or "succeed" in cls:
        return False
    value = row.get("value", "").lower()
    return ("headless" in value) or (
        value == "true" and "webdriver" in row.get("name", "").lower()
    )


# Sentinel rows this probe is known to always render, and a row-count floor —
# both exist so a page that never loaded (network outage, probe redesign,
# timeout) reports as unusable instead of silently returning "0 FAIL", which
# is byte-identical to a genuinely clean result. See MIN_USABLE_CHARS in
# evaluation/stealth_measurement.py for the same problem on a different probe.
_SENTINEL_ROW_NAMES = ("WebDriver", "User Agent")
_MIN_USABLE_ROWS = 20


async def measure(stealth: bool, timeout: float) -> list[dict[str, str]]:
    async with Browser(headless=True, stealth=stealth) as browser:
        async with asyncio.timeout(timeout):
            page = await browser.open(PROBE_URL)
            rows = await _wait_for_stable_table(page, timeout=timeout - 2)
    return rows


def _check_usable(rows: list[dict[str, str]], label: str) -> str | None:
    """None if `rows` looks like a real render; otherwise the reason it does
    not, so a caller can tell a genuinely clean 0-FAIL result apart from a
    probe that silently never loaded."""
    if len(rows) < _MIN_USABLE_ROWS:
        return f"{label}: only {len(rows)} rows (expected >= {_MIN_USABLE_ROWS})"
    names = " ".join(r["name"] for r in rows)
    missing = [s for s in _SENTINEL_ROW_NAMES if s not in names]
    if missing:
        return f"{label}: missing sentinel row(s) {missing}"
    return None


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--save-json", default=None,
        help="Write the raw before/after row lists to this path (for audit trail).",
    )
    args = parser.parse_args()

    print(f"chrome executable: {find_chrome()}")

    before = await measure(stealth=False, timeout=args.timeout)
    after = await measure(stealth=True, timeout=args.timeout)

    if args.save_json:
        await asyncio.to_thread(
            Path(args.save_json).write_text,
            json.dumps({"before": before, "after": after}, indent=2),
        )
        print(f"raw rows saved to {args.save_json}")

    unusable = [
        reason for reason in (
            _check_usable(before, "stealth=False"),
            _check_usable(after, "stealth=True"),
        ) if reason
    ]

    before_by_name = {r["name"]: r for r in before}
    after_by_name = {r["name"]: r for r in after}
    names = list(before_by_name) + [n for n in after_by_name if n not in before_by_name]

    width = max((len(n) for n in names), default=10)
    print(f"\n{'signal'.ljust(width)}  {'stealth=False'.ljust(30)}  stealth=True")
    for name in names:
        b = before_by_name.get(name)
        a = after_by_name.get(name)
        b_str = f"{b['value']!r} ({'FAIL' if _is_failed(b) else 'pass'})" if b else "MISSING"
        a_str = f"{a['value']!r} ({'FAIL' if _is_failed(a) else 'pass'})" if a else "MISSING"
        print(f"{name.ljust(width)}  {b_str.ljust(30)}  {a_str}")

    b_fails = sum(1 for r in before if _is_failed(r))
    a_fails = sum(1 for r in after if _is_failed(r))
    print(f"\ntotal rows: before={len(before)} after={len(after)}")
    print(f"total FAIL rows: before={b_fails} after={a_fails}")

    if unusable:
        print(
            "\n" + "\n".join(unusable) + "\nA run that did not render is NOT a "
            "zero-FAIL result — do not record these counts as a measurement.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
