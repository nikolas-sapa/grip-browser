"""Interaction-to-reveal evaluation: does `page.read(interact=True)` recover content
that plain `page.read()` and a static HTTP fetch cannot?

Method
------
Each URL is read four ways: a static fetch, and three grip reads split across two
tabs so that elapsed page-lifetime cannot be mistaken for interaction:

  static       — plain HTTP GET, tags stripped. Reused unmodified from run_reach.py.
  tab A: read(), then read(interact=True) — the arm under test.
  tab B: read(), sleep for exactly as long as tab A's read(interact=True) took, then
         read() again with NO interaction — the time-control arm.

The time-control arm exists because `read(interact=True)` is not just "click, then
read" — it is "click, wait up to 1s for block growth per interaction round, then
read", and that waiting is elapsed wall-clock during which a hydrating page can keep
rendering on its own. Without a same-duration no-interaction comparison, "interaction
revealed N chars" and "the page rendered N more chars in the next second regardless"
are indistinguishable, and that's exactly the class of arm-asymmetry bug this
project's other evaluations were built to catch (see README.md's whitespace/entity
bugs, SILENT_FAILURE.md's threshold bug). A page only counts as gaining content from
*interaction* if tab A gained real content AND tab B's gain over the same elapsed
time was at or below the noise floor.

Gain is measured two ways: raw character delta and new blocks (blocks whose text
wasn't present in the prior read on the same tab). A block-set diff is used rather
than a length threshold alone because length deltas alone cannot distinguish "35 new
chars of real content" from "35 chars of layout jitter" — the former shows up as new
blocks, the latter as within-block text.

Every row also carries a marker (first 12 words of the longest newly-revealed block
on tab A, chosen by the same fixed rule as run_reach.py — not hand-picked) and
whether that marker appears in the static fetch. Note this cannot distinguish
"revealed by interaction" from "revealed by hydration" either — both are absent from
raw HTML — so it answers a different question (is a browser needed at all) than the
time-control arm (is the *click* needed).

Cost is timed on tab A: read() and read(interact=True) wall-clock, so the overhead of
the interaction loop itself is visible per page.

Run: .venv/bin/python -m evaluation.run_interaction
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from evaluation.interaction_corpus import CORPUS
from evaluation.run_reach import normalise, static_fetch
from grip.browser import Browser

MARKER_WORDS = 12
MIN_BLOCK_WORDS = 15
# Below this, a character delta is treated as noise (whitespace/ad-slot jitter
# between two evaluate() calls a few hundred ms apart), not a real reveal — the
# hubspot.com/pricing control below actually went *down* 29 chars between calls,
# which is exactly this kind of jitter, not a negative reveal.
NOISE_FLOOR_CHARS = 50


@dataclass
class Row:
    category: str
    url: str
    static_chars: int
    static_status: int | str
    noninteract_chars: int
    noninteract_blocks: int
    noninteract_ms: int
    interact_chars: int
    interact_blocks: int
    interact_ms: int
    gain_chars: int
    new_block_count: int
    marker: str
    marker_in_static: bool
    control_gain_chars: int
    control_new_block_count: int
    note: str = ""

    @property
    def raw_gained(self) -> bool:
        """Tab A alone: interact=True returned more than plain read(). Does not
        rule out hydration — see `gained`."""
        return self.gain_chars > NOISE_FLOOR_CHARS and self.new_block_count > 0

    @property
    def gained(self) -> bool:
        """The claim that matters: tab A gained content AND the same elapsed time
        with no interaction (tab B) did not gain a comparable amount. A page that
        gains on both tabs is hydrating on its own, not being unlocked by the
        click/scroll."""
        return self.raw_gained and self.control_gain_chars <= NOISE_FLOOR_CHARS


def pick_marker(new_texts: list[str]) -> str:
    """Fixed rule, applied identically to every page: the longest newly-revealed
    block. Not chosen by hand, so it cannot be chosen to flatter."""
    candidates = [t for t in new_texts if len(t.split()) >= MIN_BLOCK_WORDS]
    if not candidates:
        return ""
    longest = max(candidates, key=len)
    return " ".join(longest.split()[:MARKER_WORDS])


async def main() -> None:
    rows: list[Row] = []
    async with Browser(headless=True, stealth=True) as browser:
        for category, url in CORPUS:
            note = ""
            n_chars = n_blocks = n_ms = 0
            i_chars = i_blocks = i_ms = 0
            marker = ""
            marker_in_static = False
            new_block_count = 0
            c_gain_chars = c_new_block_count = 0

            # Tab A: the arm under test.
            page = None
            try:
                page = await asyncio.wait_for(browser.open(url), timeout=30)

                t0 = time.monotonic()
                doc0 = await page.read()
                n_ms = int((time.monotonic() - t0) * 1000)
                n_chars, n_blocks = len(doc0.text), len(doc0.blocks)
                before_texts = {b.text for b in doc0.blocks}

                t0 = time.monotonic()
                doc1 = await page.read(interact=True)
                i_ms = int((time.monotonic() - t0) * 1000)
                i_chars, i_blocks = len(doc1.text), len(doc1.blocks)

                new_texts = [b.text for b in doc1.blocks if b.text not in before_texts]
                new_block_count = len(new_texts)
                marker = pick_marker(new_texts)
            except Exception as e:
                note = f"browser error: {type(e).__name__}"
            finally:
                if page is not None:
                    # Teardown: nothing useful to report if closing fails.
                    with contextlib.suppress(Exception):
                        await page.close()

            # Tab B: time control. Fresh navigation, no interaction, same elapsed
            # wait as tab A's read(interact=True) took — isolates "does waiting
            # this long by itself gain content" from "does clicking gain content".
            page = None
            try:
                page = await asyncio.wait_for(browser.open(url), timeout=30)
                doc_a = await page.read()
                await asyncio.sleep(max(0.0, i_ms / 1000))
                doc_b = await page.read()
                before_texts_b = {b.text for b in doc_a.blocks}
                new_texts_b = [b.text for b in doc_b.blocks if b.text not in before_texts_b]
                c_new_block_count = len(new_texts_b)
                c_gain_chars = len(doc_b.text) - len(doc_a.text)
            except Exception as e:
                note = note or f"control error: {type(e).__name__}"
            finally:
                if page is not None:
                    # Teardown: nothing useful to report if closing fails.
                    with contextlib.suppress(Exception):
                        await page.close()

            static_text, status = static_fetch(url)
            if marker:
                marker_in_static = normalise(marker) in normalise(static_text)

            rows.append(Row(
                category=category, url=url,
                static_chars=len(static_text), static_status=status,
                noninteract_chars=n_chars, noninteract_blocks=n_blocks,
                noninteract_ms=n_ms,
                interact_chars=i_chars, interact_blocks=i_blocks, interact_ms=i_ms,
                gain_chars=i_chars - n_chars, new_block_count=new_block_count,
                marker=marker[:70], marker_in_static=marker_in_static,
                control_gain_chars=c_gain_chars,
                control_new_block_count=c_new_block_count, note=note,
            ))
            r = rows[-1]
            print(
                f"{'GAIN' if r.gained else ('HYDRATION' if r.raw_gained else '----')}  "
                f"[{category:14}] {url[:50]:52} "
                f"+{r.gain_chars:>6,}ch (ctrl +{r.control_gain_chars:>6,}ch)  "
                f"{r.noninteract_ms:>5}ms->{r.interact_ms:>5}ms",
                flush=True,
            )
            await asyncio.sleep(0.5)

    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rows": [asdict(r) for r in rows],
    }
    # ASYNC230: a single blocking write after all fetching is done, not in a hot path.
    with Path("evaluation/interaction_results.json").open("w") as f:  # noqa: ASYNC230
        json.dump(out, f, indent=1)

    report(rows)


def report(rows: list[Row]) -> None:
    print("\n" + "=" * 78)
    print(f"{'category':16}{'n':>4}{'gained':>8}{'hydration':>11}"
          f"{'median +ch':>12}{'median +ms':>12}")
    for cat in ("api_reference", "accordion_ui", "control"):
        group = [r for r in rows if r.category == cat]
        if not group:
            continue
        gained = sum(r.gained for r in group)
        hydration = sum(r.raw_gained and not r.gained for r in group)
        ch = sorted(r.gain_chars for r in group)
        ms = sorted(r.interact_ms - r.noninteract_ms for r in group)
        mid_ch = ch[len(ch) // 2]
        mid_ms = ms[len(ms) // 2]
        print(f"{cat:16}{len(group):>4}{gained:>7}/{len(group)}{hydration:>10}"
              f"{mid_ch:>10,}{mid_ms:>11,}ms")

    hydration_rows = [r for r in rows if r.raw_gained and not r.gained]
    if hydration_rows:
        print(f"\nRaw gains that did NOT survive the time control (page hydrated "
              f"on its own,\nnot because of the click): {len(hydration_rows)}")
        for r in hydration_rows:
            print(f"  [{r.category:14}] {r.url[:60]:62} tab A +{r.gain_chars:,} "
                  f"chars, tab B (same wait, no click) +{r.control_gain_chars:,} chars")

    false_positives = [r for r in rows if r.category != "api_reference" and r.gained]
    print(f"\nFalse positives (accordion_ui/control pages where interact=True "
          f"gained content\nthat survived the time control): {len(false_positives)}")
    for r in false_positives:
        print(f"  [{r.category:14}] {r.url[:60]:62} +{r.gain_chars:,} chars, "
              f"{r.new_block_count} new blocks")

    gains = [r for r in rows if r.gained]
    if gains:
        print(f"\nPages where interact=True recovered content the time control "
              f"rules out as\nhydration: {len(gains)}/{len(rows)}")
        for r in gains:
            print(f"  [{r.category:14}] {r.url[:60]:62} "
                  f"+{r.gain_chars:>6,} chars, marker_in_static={r.marker_in_static}")
        also_in_static = sum(r.marker_in_static for r in gains)
        print(f"\nOf those, static fetch also had the revealed marker text: "
              f"{also_in_static}/{len(gains)}")

    errors = [r for r in rows if r.note]
    if errors:
        print("\nPages that errored:")
        for r in errors:
            print(f"  {r.url[:60]:62} {r.note}")

    all_ms = [(r.noninteract_ms, r.interact_ms) for r in rows if not r.note]
    if all_ms:
        avg_n = sum(x[0] for x in all_ms) / len(all_ms)
        avg_i = sum(x[1] for x in all_ms) / len(all_ms)
        print(f"\nCost: mean read() {avg_n:,.0f}ms vs mean read(interact=True) "
              f"{avg_i:,.0f}ms ({avg_i / avg_n:.1f}x)")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
