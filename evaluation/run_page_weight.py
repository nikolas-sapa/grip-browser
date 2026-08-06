"""Page-weight evaluation: how many bytes does a real browser fetch actually pull
over the wire, and does the proxy-cost conclusion in `docs/research/proxy-pricing.md`
survive once the corpus is not just developer documentation?

`proxy-pricing.md` measured 0.50 MB/page and used it to conclude residential
proxies at $4/GB keep grip under Tavily's $0.049/query. That figure came from a
corpus built for the reach evaluation (`evaluation/corpus.py`), never validated as
representative of what a real user of this tool fetches. This script measures five
categories — developer docs, news, e-commerce, blog, reference — to find out where
that conclusion actually holds.

Method
------
For each (URL, arm) pair, a **fresh Chrome process with a fresh temp profile** is
launched (`grip.browser.Browser`, same as `proxy-pricing.md`'s method) so every
measurement is a cold cache — the right assumption for a rotating residential
proxy, where a new IP has no cache to reuse. `Network.setCacheDisabled` is set on
top of that, since a fresh profile alone does not rule out Chrome's in-memory
cache or a service worker within one page load.

Two arms per URL:
  full    — everything loads, nothing blocked.
  blocked — `Fetch.enable` at `requestStage: "Request"` fails every request whose
            `resourceType` is Image, Font, Media or Stylesheet with
            `BlockedByClient`. Script is deliberately NOT blocked (matches
            `proxy-pricing.md` — the reach evaluation found content ships in the
            initial HTML/JS, so blocking JS would delete the differentiator).

Bytes are `Network.loadingFinished.encodedDataLength` summed per page — bytes on
the wire including headers, which is what a proxy meters. A blocked request never
reaches the network layer at all (Fetch intercepts at Request stage, before the
fetch is dispatched), so it contributes 0 bytes, which is the correct billing
model for a real blocking proxy config.

Grip's own classifier (`page.snapshot().page_error`) plus the main-document HTTP
status plus extracted character count are used to classify each row `loaded` /
`interstitial` / `failed`. Only `loaded` rows enter the category means — byte count
alone cannot distinguish "light page" from "block page returning a 40 KB CAPTCHA",
and folding blocked pages into an average would produce a false-favorable result
the same way `proxy-pricing.md` had to explicitly exclude a Cloudflare interstitial
from its own numbers.

Settle window: 4 seconds after the load event fires, identical in both arms, to
give lazy-loaded assets (recognised in `proxy-pricing.md` as a truncation risk on
pages like bbc.com) a chance to land. Still a floor, not a ceiling — see
PAGE_WEIGHT.md limitations.

Run: .venv/bin/python -m evaluation.run_page_weight
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass

from evaluation.page_weight_corpus import CORPUS
from grip.browser import Browser
from grip.cdp.engine import CDPEngine
from grip.page import Page

SETTLE_SECONDS = 4.0
PER_URL_TIMEOUT = 50.0
BLOCKED_TYPES = {"Image", "Font", "Media", "Stylesheet"}
MIN_LOADED_CHARS = 200  # below this, "loaded" is indistinguishable from a stub


@dataclass
class Row:
    category: str
    url: str
    arm: str
    status: str  # loaded / interstitial / failed
    reason: str
    bytes_total: int
    mb_total: float
    request_count: int
    doc_status: int
    page_error: str
    chars: int


async def _open_instrumented_page(
    browser: Browser, blocked: bool
) -> tuple[Page, dict]:
    """Create a tab on `browser` and wire up byte accounting (and, if `blocked`,
    resource-type interception) *before* navigating — mirrors what
    `Browser.open()` does internally, but that method navigates before handing
    the Page back, which is too late to attach listeners for the load we care
    about. Not a modification of grip/, just driving its public Page/CDPEngine
    classes with an extra listener, same pattern the module docstring in
    grip/page.py invites."""
    await browser._connect()
    assert browser._engine is not None
    result = await browser._engine.send(
        "Target.createTarget", {"url": "about:blank"}
    )
    target_id = result["targetId"]
    page_engine = CDPEngine()
    await page_engine.connect(
        f"ws://localhost:{browser._port}/devtools/page/{target_id}"
    )
    page = Page(
        engine=page_engine,
        trace=browser.trace,
        target_id=target_id,
        safe=browser._safe,
        closer=browser._close_target,
    )
    browser._pages.append(page)

    stats = {"bytes": 0, "requests": 0}

    def on_finished(params: dict) -> None:
        stats["bytes"] += params.get("encodedDataLength", 0)
        stats["requests"] += 1

    page_engine.on("Network.loadingFinished", on_finished)

    await page_engine.send("Network.enable")
    await page_engine.send("Network.setCacheDisabled", {"cacheDisabled": True})

    if blocked:
        await page_engine.send(
            "Fetch.enable",
            {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]},
        )
        handled: set[str] = set()

        def on_paused(params: dict) -> None:
            asyncio.create_task(_handle_paused(page_engine, params, handled))

        page_engine.on("Fetch.requestPaused", on_paused)

    return page, stats


async def _handle_paused(engine: CDPEngine, params: dict, handled: set[str]) -> None:
    request_id = params["requestId"]
    if request_id in handled:
        return  # a redirect can re-fire requestPaused; continuing twice errors
    handled.add(request_id)
    resource_type = params.get("resourceType", "Other")
    try:
        if resource_type in BLOCKED_TYPES:
            await engine.send(
                "Fetch.failRequest",
                {"requestId": request_id, "errorReason": "BlockedByClient"},
            )
        else:
            await engine.send("Fetch.continueRequest", {"requestId": request_id})
    except Exception:  # noqa: BLE001,S110 - a lost race on a torn-down page, not fatal
        pass


async def measure(category: str, url: str, arm: str) -> Row:
    blocked = arm == "blocked"
    browser = Browser(headless=True, stealth=True)
    try:
        async with browser:
            page, stats = await _open_instrumented_page(browser, blocked)
            try:
                await page.goto(url, timeout=30)
                await asyncio.sleep(SETTLE_SECONDS)
                doc_status = page._status_code
                page_error = ""
                chars = 0
                try:
                    snap = await page.snapshot()
                    if snap.page_error is not None:
                        page_error = snap.page_error.type.value
                    doc = await page.read()
                    chars = len(doc.text)
                except Exception as e:  # noqa: BLE001 - byte count still stands
                    page_error = page_error or f"read_error:{type(e).__name__}"
            finally:
                await page.close()

            if page_error:
                status, reason = "interstitial", page_error
            elif doc_status and not (200 <= doc_status < 400):
                status, reason = "failed", f"http_{doc_status}"
            elif chars < MIN_LOADED_CHARS:
                status, reason = "failed", f"stub_content_{chars}_chars"
            else:
                status, reason = "loaded", ""

            return Row(
                category=category, url=url, arm=arm,
                status=status, reason=reason,
                bytes_total=stats["bytes"],
                mb_total=round(stats["bytes"] / (1024 * 1024), 4),
                request_count=stats["requests"],
                doc_status=doc_status, page_error=page_error, chars=chars,
            )
    except Exception as e:  # noqa: BLE001 - a benchmark must survive any one URL
        return Row(
            category=category, url=url, arm=arm,
            status="failed", reason=f"error:{type(e).__name__}",
            bytes_total=0, mb_total=0.0, request_count=0,
            doc_status=0, page_error="", chars=0,
        )


async def measure_with_timeout(category: str, url: str, arm: str) -> Row:
    try:
        return await asyncio.wait_for(
            measure(category, url, arm), timeout=PER_URL_TIMEOUT
        )
    except TimeoutError:
        return Row(
            category=category, url=url, arm=arm,
            status="failed", reason="timeout",
            bytes_total=0, mb_total=0.0, request_count=0,
            doc_status=0, page_error="", chars=0,
        )


async def main() -> None:
    rows: list[Row] = []
    # Sequential, not concurrent: parallel Chromes share one network link and one
    # IP, and contention truncates slow pages at the settle deadline — a bias that
    # (like every other measurement shortcut) pushes MB/page down, i.e. toward the
    # favourable conclusion. Slower, but the number is worth trusting.
    for category, url in CORPUS:
        for arm in ("full", "blocked"):
            row = await measure_with_timeout(category, url, arm)
            rows.append(row)
            print(
                f"{row.status:12}[{arm:7}] {category:10} "
                f"{row.mb_total:>7.3f} MB  {row.reason or 'ok':<24} {url[:60]}",
                flush=True,
            )

    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "settle_seconds": SETTLE_SECONDS,
        "rows": [asdict(r) for r in rows],
    }
    with open("evaluation/page_weight_results.json", "w") as f:  # noqa: ASYNC230
        json.dump(out, f, indent=1)

    report(rows)


def report(rows: list[Row]) -> None:
    categories = sorted({r.category for r in rows})
    print("\n" + "=" * 78)
    print(f"{'category':11}{'arm':9}{'n':>4}{'loaded':>8}{'excl.':>7}"
          f"{'mean MB':>10}{'median MB':>11}")
    summary: dict[tuple[str, str], dict] = {}
    for cat in categories:
        for arm in ("full", "blocked"):
            group = [r for r in rows if r.category == cat and r.arm == arm]
            loaded = [r for r in group if r.status == "loaded"]
            excluded = [r for r in group if r.status != "loaded"]
            sizes = sorted(r.mb_total for r in loaded)
            mean = sum(sizes) / len(sizes) if sizes else 0.0
            median = sizes[len(sizes) // 2] if sizes else 0.0
            summary[(cat, arm)] = {
                "n": len(group), "loaded": len(loaded), "excluded": len(excluded),
                "mean": mean, "median": median,
                "excluded_reasons": [f"{r.url} ({r.reason})" for r in excluded],
            }
            print(f"{cat:11}{arm:9}{len(group):>4}{len(loaded):>8}"
                  f"{len(excluded):>7}{mean:>10.3f}{median:>11.3f}")

    if any(s["excluded"] for s in summary.values()):
        print("\nExcluded from category means (not loaded — see reason):")
        for (cat, arm), s in summary.items():
            for item in s["excluded_reasons"]:
                print(f"  [{cat:10}{arm:8}] {item}")

    # Cost arithmetic, reusing docs/research/proxy-pricing.md's own inputs:
    # grip $0.025/query baseline, Tavily $0.049/query, 8 pages/query.
    grip_baseline = 0.025
    tavily = 0.049
    pages_per_query = 8
    rates_per_gb = [8.50, 6.00, 4.00, 2.75, 1.75, 0.59]
    print("\n" + "=" * 78)
    print("Cost per query = $0.025 + (mean MB/page x 8 pages / 1024) x $/GB")
    print(f"Tavily baseline: ${tavily}/query\n")
    for cat in categories:
        for arm in ("full", "blocked"):
            s = summary[(cat, arm)]
            if s["loaded"] == 0:
                print(f"[{cat:10}{arm:8}] no loaded pages — cost cannot be computed")
                continue
            print(f"[{cat:10}{arm:8}] mean {s['mean']:.3f} MB/page "
                  f"({s['loaded']}/{s['n']} loaded)")
            for rate in rates_per_gb:
                proxy_cost = (s["mean"] * pages_per_query / 1024) * rate
                total = grip_baseline + proxy_cost
                verdict = "beats Tavily" if total < tavily else "LOSES to Tavily"
                print(f"    ${rate:>5.2f}/GB -> proxy ${proxy_cost:.4f} "
                      f"+ ${grip_baseline} = ${total:.4f}  {verdict}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
