"""
Measurement harness for grip's hot paths: snapshot(), read(), element matching
(click/type), and the raw CDP round trip. Local http.server fixtures (small,
medium, large-DOM) keep results deterministic and offline.

Run: .venv/bin/python benchmarks/bench_grip.py
"""
from __future__ import annotations

import asyncio
import statistics
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from grip.browser import Browser
from grip.cdp.shadow import DISCOVER_ELEMENTS_JS, READ_CONTENT_JS
from grip.compression.delta import build_delta
from grip.compression.refs import RefRegistry
from grip.compression.summarizer import Summarizer
from grip.security.sanitizer import RawElement

N_RUNS = 15


# --------------------------------------------------------------------------
# Fixtures: small (a real-world-sized page), medium, and a deliberately large
# DOM (thousands of elements) so quadratic behaviour would show up.
# --------------------------------------------------------------------------

def _build_html(n_interactive: int, n_paragraphs: int) -> bytes:
    parts = ["<html><body><main>"]
    parts.append("<h1>Benchmark fixture</h1>")
    for i in range(n_paragraphs):
        parts.append(
            f"<p>Paragraph {i} with some representative prose text so the "
            f"content-extraction JS has real strings to walk and score, not "
            f"just empty tags. Lorem ipsum dolor sit amet number {i}.</p>"
        )
    for i in range(n_interactive):
        kind = i % 4
        if kind == 0:
            parts.append(f'<button id="b{i}">Button {i}</button>')
        elif kind == 1:
            parts.append(f'<a href="/page/{i}">Link {i}</a>')
        elif kind == 2:
            parts.append(f'<input placeholder="field {i}" />')
        else:
            parts.append(f'<select><option>opt{i}</option></select>')
    parts.append("</main></body></html>")
    return "".join(parts).encode()


def _build_sparse_html(n_wrappers: int, n_interactive: int) -> bytes:
    """Real pages are mostly non-interactive wrapper divs/spans around a
    small number of interactive elements — the "large" fixture above is
    unusually dense (60% interactive) and under-represents that shape."""
    parts = ["<html><body><main>"]
    for i in range(n_wrappers):
        parts.append(f'<div class="wrap{i}"><span>text {i}</span></div>')
    for i in range(n_interactive):
        parts.append(f'<button id="b{i}">Button {i}</button>')
    parts.append("</main></body></html>")
    return "".join(parts).encode()


FIXTURES = {
    "small": _build_html(n_interactive=20, n_paragraphs=10),
    "medium": _build_html(n_interactive=300, n_paragraphs=100),
    "large": _build_html(n_interactive=3000, n_paragraphs=2000),
    "sparse": _build_sparse_html(n_wrappers=5000, n_interactive=150),
}


def _make_handler(page: bytes) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args: object) -> None:
            pass

    return _Handler


def _serve(page: bytes) -> tuple[HTTPServer, str]:
    # Loopback fixture: NavigationPolicy refuses private addresses by default
    # (SSRF guard), so every Browser here opts in with allow_private=True.
    httpd = HTTPServer(("127.0.0.1", 0), _make_handler(page))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_port}"


def _stats(samples: list[float]) -> str:
    med = statistics.median(samples) * 1000
    lo, hi = min(samples) * 1000, max(samples) * 1000
    return f"median={med:6.2f}ms  min={lo:6.2f}  max={hi:6.2f}  n={len(samples)}"


async def _time_calls(fn, n: int = N_RUNS) -> list[float]:
    samples = []
    for _ in range(n):
        t0 = time.monotonic()
        await fn()
        samples.append(time.monotonic() - t0)
    return samples


# --------------------------------------------------------------------------
# Browser-backed benchmarks
# --------------------------------------------------------------------------

async def bench_snapshot(browser: Browser, url: str, label: str) -> None:
    page = await browser.open(url)
    await page.snapshot()  # warm-up: first hit pays connection/JIT costs
    samples = await _time_calls(page.snapshot)
    print(f"  snapshot()          [{label:6s}] {_stats(samples)}  elements={len(page._current_snapshot.elements)}")
    await page.close()


async def bench_read(browser: Browser, url: str, label: str) -> None:
    page = await browser.open(url)
    await page.read()
    samples = await _time_calls(page.read)
    print(f"  read()               [{label:6s}] {_stats(samples)}")
    await page.close()


async def bench_engine_roundtrip(browser: Browser, url: str, label: str) -> None:
    page = await browser.open(url)
    await page._engine.send("Runtime.evaluate", {"expression": "1+1", "returnByValue": True})

    async def _trivial() -> None:
        await page._engine.send("Runtime.evaluate", {"expression": "1+1", "returnByValue": True})

    samples = await _time_calls(_trivial)
    print(f"  engine.send() (noop) [{label:6s}] {_stats(samples)}")
    await page.close()


async def bench_discover_vs_readcontent(browser: Browser, url: str, label: str) -> None:
    """Isolate JS execution time from round-trip overhead: a no-op eval gives
    the round-trip floor; DISCOVER/READ_CONTENT eval time above that floor is
    JS-side cost, which Python-side changes cannot touch."""
    page = await browser.open(url)

    async def _discover() -> None:
        await page._engine.send(
            "Runtime.evaluate", {"expression": DISCOVER_ELEMENTS_JS, "returnByValue": True}
        )

    async def _read_content() -> None:
        await page._engine.send(
            "Runtime.evaluate", {"expression": READ_CONTENT_JS, "returnByValue": True}
        )

    await _discover()
    await _read_content()
    d_samples = await _time_calls(_discover)
    r_samples = await _time_calls(_read_content)
    print(f"  DISCOVER_ELEMENTS_JS [{label:6s}] {_stats(d_samples)}")
    print(f"  READ_CONTENT_JS      [{label:6s}] {_stats(r_samples)}")
    await page.close()


async def bench_snapshot_sequential_vs_concurrent(browser: Browser, url: str, label: str) -> None:
    """Does batching the 3 independent CDP calls inside snapshot() with
    asyncio.gather beat running them sequentially? Same calls, same page."""
    page = await browser.open(url)
    await page._ensure_initialized()

    async def _sequential() -> None:
        await page._discover_elements()
        await page._get_page_text()
        await page._get_page_info()

    async def _concurrent() -> None:
        await asyncio.gather(
            page._discover_elements(), page._get_page_text(), page._get_page_info()
        )

    await _sequential()
    await _concurrent()
    seq = await _time_calls(_sequential)
    con = await _time_calls(_concurrent)
    print(f"  3 calls sequential   [{label:6s}] {_stats(seq)}")
    print(f"  3 calls gather()     [{label:6s}] {_stats(con)}")
    await page.close()


async def bench_click_type_matching(browser: Browser, url: str, label: str) -> None:
    page = await browser.open(url)
    await page.snapshot()

    def _match_last() -> None:
        # Worst case for the linear scans in _find_element_index/_find_input_index:
        # a description that only matches the last element.
        el = page._current_snapshot.elements[-1]
        desc = el.text or el.placeholder or el.role
        page._find_element_index(desc)
        page._find_input_index(desc)

    t0 = time.monotonic()
    for _ in range(N_RUNS):
        _match_last()
    dt = (time.monotonic() - t0) / N_RUNS
    print(f"  element matching     [{label:6s}] median~={dt * 1000:6.2f}ms (pure Python, no CDP)")
    await page.close()


# --------------------------------------------------------------------------
# Pure-Python compression pipeline (no browser) — isolates algorithmic cost
# from JS/round-trip cost, at element counts up to 5000.
# --------------------------------------------------------------------------

def _synthetic_raw_elements(n: int) -> list[RawElement]:
    tags = ["button", "a", "input", "select"]
    return [
        RawElement(
            tag=tags[i % 4],
            role=tags[i % 4],
            text=f"element text {i} with some words",
            placeholder=None,
            in_shadow_dom=False,
            cx=i % 800,
            cy=i // 10,
            computed_display="block",
            computed_visibility="visible",
            computed_opacity="1",
            aria_hidden=False,
            width=100,
            height=20,
            href=f"/path/{i}" if tags[i % 4] == "a" else None,
            handle=f"h{i}",
        )
        for i in range(n)
    ]


def bench_compression_pipeline() -> None:
    print("\nPython-side compression pipeline (no browser, isolates algorithmic cost):")
    for n in (100, 1000, 5000):
        raw = _synthetic_raw_elements(n)
        summarizer = Summarizer()
        refs = RefRegistry()

        t0 = time.monotonic()
        snap = summarizer.build(version=1, url="http://x", title="t", raw_elements=raw, page_text="hello " * 500)
        for el in snap.elements:
            el.ref = refs.assign(el.handle)
        snap.tokens_estimated = summarizer.count_tokens(summarizer.format(snap))
        build_delta(snap, snap)
        dt = time.monotonic() - t0
        print(f"  n={n:5d} elements: {dt * 1000:7.2f}ms total (build+refs+tokens+delta)")


async def main() -> None:
    bench_compression_pipeline()

    async with Browser(headless=True, allow_private=True) as browser:
        for label, html in FIXTURES.items():
            httpd, url = _serve(html)
            try:
                print(f"\n=== fixture: {label} ===")
                await bench_engine_roundtrip(browser, url, label)
                await bench_snapshot_sequential_vs_concurrent(browser, url, label)
                await bench_discover_vs_readcontent(browser, url, label)
                await bench_snapshot(browser, url, label)
                await bench_read(browser, url, label)
                await bench_click_type_matching(browser, url, label)
            finally:
                httpd.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
