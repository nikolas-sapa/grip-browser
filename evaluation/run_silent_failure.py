"""Silent-failure evaluation: does grip know when a fetch didn't work?

Context
-------
The reach evaluation (`run_reach.py`) falsified the claim that a browser sees
content static fetch cannot — the gap was zero across 33 URLs. This evaluation
tests the second surviving hypothesis: pages that fail while still returning
HTTP 200 — consent walls, anti-bot interstitials, JS-required shells, soft
404s. A static fetcher has no signal that anything went wrong; it hands a
retrieval pipeline plausible-looking prose and the pipeline cites it. grip has
`snapshot.page_error` and `read()` returning zero (or near-zero) blocks.

Method
------
Every URL returns HTTP 200 (or a status a naive pipeline would still accept).
For each one, both arms fetch it:

  static arm   — plain HTTP GET, tags stripped, same helpers as run_reach.py.
                 Scored against a **naive quality gate**: status 200 and more
                 than 500 characters of extracted text. This is what a
                 pipeline that doesn't specifically check for blocking would
                 use to decide "this is a usable source".
  browser arm  — grip: `page.snapshot()` for `page_error`, `page.read()` for
                 block count and character count.

The corpus (`silent_failure_corpus.py`) carries a hand-set `expect_failure`
ground truth per URL, checked by inspecting the actual extracted text — not
inferred from the category label. It includes control pages on equal footing
with failure pages specifically so this evaluation can produce false
positives, not just true positives.

Scoring, both directions:
  true positive  — a page that actually failed, where static fetch's output
                    would clear the naive gate (silently accepted as good)
                    but grip flagged it (page_error, or zero/near-zero blocks).
  false positive — a control page, genuinely fine, that grip flags anyway.
  self-reported   — a page that failed where static ALSO failed the naive gate
                    (short text or bad status). Not silent: a competent
                    pipeline would have caught it without grip.
  missed          — a page that failed where NEITHER arm caught it.

Run: .venv/bin/python -m evaluation.run_silent_failure
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass

from evaluation.run_reach import static_fetch
from evaluation.silent_failure_corpus import CORPUS
from grip.browser import Browser

# A pipeline that only sanity-checks length would treat this much prose as a
# usable source. Not tuned per-page — one fixed threshold, applied to every URL.
NAIVE_GATE_MIN_CHARS = 500

# grip is considered to have "flagged" a page if it reports a page_error, or if
# read() fails the *same* bar static's output is held to. Using one shared
# threshold instead of a separate, laxer one for grip matters: an earlier draft
# of this script used 50 chars here against static's 500, which hid the real
# effect. grip's read() strips boilerplate, so a page with real content but no
# substance left after stripping chrome falls below the bar that static's
# padded output cleared — that gap is the signal, and it only shows up when
# both arms are held to the same line.
GRIP_EMPTY_CHARS = NAIVE_GATE_MIN_CHARS


@dataclass
class Row:
    category: str
    url: str
    expect_failure: bool
    static_status: int | str
    static_chars: int
    static_passes_naive_gate: bool
    grip_error_type: str
    grip_blocks: int
    grip_chars: int
    grip_flagged: bool
    outcome: str
    note: str = ""


def classify(row_kwargs: dict) -> str:
    """Fixed rule, applied identically to every row — see module docstring."""
    expect_failure = row_kwargs["expect_failure"]
    static_pass = row_kwargs["static_passes_naive_gate"]
    grip_flagged = row_kwargs["grip_flagged"]

    if not expect_failure:
        return "false_positive" if grip_flagged else "true_negative"
    # expect_failure is True from here down
    if static_pass and grip_flagged:
        return "true_positive"
    if static_pass and not grip_flagged:
        return "missed"
    # static did not pass the naive gate: the failure was loud, not silent
    return "self_reported"


async def main() -> None:
    rows: list[Row] = []
    async with Browser(headless=True, stealth=True) as browser:
        for category, url, expect_failure in CORPUS:
            page = None
            grip_error_type, grip_blocks, grip_chars, note = "none", 0, 0, ""
            try:
                page = await asyncio.wait_for(browser.open(url), timeout=30)
                snap = await page.snapshot()
                if snap.page_error is not None:
                    grip_error_type = snap.page_error.type.value
                doc = await page.read()
                grip_blocks = len(doc.blocks)
                grip_chars = len(doc.text)
            except Exception as e:  # noqa: BLE001 - record the failure, keep going
                note = f"browser error: {type(e).__name__}"
                grip_error_type = "exception"
            finally:
                if page is not None:
                    try:
                        await page.close()
                    except Exception:  # noqa: BLE001,S110 - teardown, nothing to report
                        pass

            static_text, status = static_fetch(url)
            static_chars = len(static_text)
            static_passes_naive_gate = (
                status == 200 and static_chars > NAIVE_GATE_MIN_CHARS
            )
            grip_flagged = grip_error_type != "none" or grip_chars < GRIP_EMPTY_CHARS

            outcome = classify({
                "expect_failure": expect_failure,
                "static_passes_naive_gate": static_passes_naive_gate,
                "grip_flagged": grip_flagged,
            })

            rows.append(Row(
                category=category, url=url, expect_failure=expect_failure,
                static_status=status, static_chars=static_chars,
                static_passes_naive_gate=static_passes_naive_gate,
                grip_error_type=grip_error_type, grip_blocks=grip_blocks,
                grip_chars=grip_chars, grip_flagged=grip_flagged,
                outcome=outcome, note=note,
            ))
            print(
                f"[{outcome:15}] [{category:12}] static={static_chars:>6}c "
                f"gate={'PASS' if static_passes_naive_gate else 'fail'}  "
                f"grip={grip_error_type:16} blocks={grip_blocks:>3} "
                f"chars={grip_chars:>6}  {url[:56]}",
                flush=True,
            )
            await asyncio.sleep(0.5)

    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "naive_gate_min_chars": NAIVE_GATE_MIN_CHARS,
        "grip_empty_chars": GRIP_EMPTY_CHARS,
        "rows": [asdict(r) for r in rows],
    }
    # ASYNC230: a single blocking write after all fetching is done, not in a hot path.
    with open("evaluation/silent_failure_results.json", "w") as f:  # noqa: ASYNC230
        json.dump(out, f, indent=1)

    report(rows)


def report(rows: list[Row]) -> None:
    failures = [r for r in rows if r.expect_failure]
    controls = [r for r in rows if not r.expect_failure]

    tp = [r for r in failures if r.outcome == "true_positive"]
    missed = [r for r in failures if r.outcome == "missed"]
    self_reported = [r for r in failures if r.outcome == "self_reported"]
    fp = [r for r in controls if r.outcome == "false_positive"]
    tn = [r for r in controls if r.outcome == "true_negative"]

    print("\n" + "=" * 78)
    print(f"Failure pages (expect_failure=True): {len(failures)}")
    print(f"  static silently accepted it, grip flagged it (TRUE POSITIVE): "
          f"{len(tp)}/{len(failures)}")
    print(f"  static also rejected it — loud, not silent (self-reported): "
          f"{len(self_reported)}/{len(failures)}")
    print(f"  neither arm caught it (missed): {len(missed)}/{len(failures)}")

    print(f"\nControl pages (expect_failure=False): {len(controls)}")
    print(f"  grip wrongly flagged a good page (FALSE POSITIVE): "
          f"{len(fp)}/{len(controls)}")
    print(f"  correctly left alone (true negative): {len(tn)}/{len(controls)}")

    print(f"\n{'category':13}{'n':>4}{'TP':>5}{'self-rep':>10}{'missed':>8}{'FP':>5}")
    for cat in ("consent_wall", "js_shell", "soft_404", "anti_bot", "control"):
        group = [r for r in rows if r.category == cat]
        if not group:
            continue
        n_tp = sum(r.outcome == "true_positive" for r in group)
        n_sr = sum(r.outcome == "self_reported" for r in group)
        n_ms = sum(r.outcome == "missed" for r in group)
        n_fp = sum(r.outcome == "false_positive" for r in group)
        print(f"{cat:13}{len(group):>4}{n_tp:>5}{n_sr:>10}{n_ms:>8}{n_fp:>5}")

    if tp:
        print("\nTrue positives — static silently accepted junk, grip flagged it:")
        for r in tp:
            print(f"  [{r.category:12}] {r.url[:52]:54} "
                  f"static {r.static_chars:>6,}c (PASS)  grip {r.grip_error_type} "
                  f"blocks={r.grip_blocks} chars={r.grip_chars}")

    if fp:
        print("\nFalse positives — grip flagged a genuinely good page:")
        for r in fp:
            print(f"  [{r.category:12}] {r.url[:52]:54} "
                  f"grip {r.grip_error_type} blocks={r.grip_blocks} chars={r.grip_chars}"
                  f"  note={r.note}")

    if self_reported:
        print("\nSelf-reported — static also failed the naive gate (not silent):")
        for r in self_reported:
            print(f"  [{r.category:12}] {r.url[:52]:54} "
                  f"static {r.static_chars:>6,}c status={r.static_status}")

    if missed:
        print("\nMissed — neither arm caught the failure:")
        for r in missed:
            print(f"  [{r.category:12}] {r.url[:52]:54} "
                  f"static {r.static_chars:>6,}c (PASS)  grip {r.grip_error_type} "
                  f"blocks={r.grip_blocks} chars={r.grip_chars}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
