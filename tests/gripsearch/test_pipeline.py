"""
End-to-end retrieval against a local corpus, so ranking assertions are
deterministic and offline.
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from gripsearch import NoUsableSources, Retriever, StaticSource

CORPUS = {
    "/asyncio": b"""<html><head><title>asyncio gather</title></head><body>
      <nav><a href="/x">Home</a><a href="/y">Pricing</a></nav>
      <main>
        <h1>Running tasks concurrently</h1>
        <p>The gather function runs awaitables concurrently and returns their results.</p>
        <h2>Exceptions</h2>
        <p>If return_exceptions is False, the first raised exception propagates
           immediately to the caller of gather, and other awaitables continue running.</p>
      </main>
      <footer><p>Copyright notice, all rights reserved.</p></footer>
    </body></html>""",
    "/threads": b"""<html><head><title>threading basics</title></head><body>
      <main>
        <h1>Threads</h1>
        <p>A thread is the smallest sequence of instructions a scheduler manages
           independently, and has nothing to do with coroutines.</p>
      </main>
    </body></html>""",
    "/duplicate": b"""<html><head><title>mirror of asyncio docs</title></head><body>
      <main>
        <h1>Running tasks concurrently</h1>
        <p>If return_exceptions is False, the first raised exception propagates
           immediately to the caller of gather, and other awaitables continue running.</p>
      </main>
    </body></html>""",
    "/blocked": b"""<html><head><title>Just a moment...</title></head><body>
      <main><p>Checking your browser.</p></main></body></html>""",
    "/empty": b"""<html><head><title>Nothing here</title></head><body>
      <nav><a href="/a">Only navigation</a></nav></body></html>""",
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = CORPUS.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        # /blocked serves its interstitial with a 403, like the real thing
        self.send_response(403 if self.path == "/blocked" else 200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def base_url():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def _source(base, *paths):
    return StaticSource([f"{base}{p}" for p in paths])


def _retriever(base, *paths, **kw):
    # The fixture server is on 127.0.0.1 and NavigationPolicy refuses loopback by
    # default, so these tests must opt in explicitly — the same way a caller
    # pointing gripsearch at an internal host has to.
    return Retriever(_source(base, *paths), allow_private=True, **kw)


@pytest.mark.asyncio
async def test_relevant_passage_ranks_first(base_url):
    async with _retriever(base_url, "/threads", "/asyncio") as r:
        result = await r.search("gather exception propagates to caller")
    assert result.passages
    assert "return_exceptions" in result.passages[0].text
    assert result.passages[0].url.endswith("/asyncio")


@pytest.mark.asyncio
async def test_citation_resolves_to_the_right_heading(base_url):
    async with _retriever(base_url, "/asyncio") as r:
        result = await r.search("gather exception propagates to caller")
    top = result.passages[0]
    assert "Running tasks concurrently" in top.citation
    assert "Exceptions" in top.citation


@pytest.mark.asyncio
async def test_blocked_source_is_reported_not_dropped(base_url):
    async with _retriever(base_url, "/asyncio", "/blocked") as r:
        result = await r.search("gather")
    failed = [f for f in result.failures if f.url.endswith("/blocked")]
    assert failed, "a blocked source vanished instead of being reported"
    assert result.sources_consulted == 1


@pytest.mark.asyncio
async def test_content_free_page_is_reported(base_url):
    async with _retriever(base_url, "/asyncio", "/empty") as r:
        result = await r.search("gather")
    assert any(f.url.endswith("/empty") for f in result.failures)


@pytest.mark.asyncio
async def test_near_duplicate_passages_are_collapsed(base_url):
    async with _retriever(base_url, "/asyncio", "/duplicate") as r:
        result = await r.search("gather exception propagates to caller")
    texts = [p.text for p in result.passages]
    assert len(texts) == len(set(texts))
    hits = [t for t in texts if "return_exceptions" in t]
    assert len(hits) == 1, f"duplicate passage survived dedup: {hits}"


@pytest.mark.asyncio
async def test_chrome_never_becomes_a_passage(base_url):
    async with _retriever(base_url, "/asyncio") as r:
        result = await r.search("pricing copyright home")
    for p in result.passages:
        assert "all rights reserved" not in p.text.lower()
        assert "Pricing" not in p.text


@pytest.mark.asyncio
async def test_all_sources_failing_raises_with_the_failures_attached(base_url):
    async with _retriever(base_url, "/blocked") as r:
        with pytest.raises(NoUsableSources) as exc:
            await r.search("anything")
    assert exc.value.failures
    assert "/blocked" in str(exc.value)


@pytest.mark.asyncio
async def test_result_reports_what_it_cost(base_url):
    async with _retriever(base_url, "/asyncio") as r:
        result = await r.search("gather")
    assert result.elapsed_s > 0
    assert result.tokens_estimated > 0
    assert result.sources_consulted == 1


@pytest.mark.asyncio
async def test_searching_outside_the_context_manager_is_an_error():
    r = Retriever(StaticSource(["http://127.0.0.1:1/x"]))
    with pytest.raises(RuntimeError, match="async with"):
        await r.search("q")
