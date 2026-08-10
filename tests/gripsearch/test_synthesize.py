"""
Synthesis is opt-in and fully offline-testable: `SynthesisModel` is a narrow
single-method protocol, so a fake stands in for any real LLMAdapter with no
network and no API key.
"""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gripsearch import Passage, Retriever, StaticSource
from gripsearch.synthesize import synthesize


class FakeModel:
    def __init__(self, response: str):
        self._response = response

    async def complete(self, prompt: str) -> str:
        return self._response


def _passages(n: int) -> list[Passage]:
    return [
        Passage(text=f"text {i}", url=f"https://example.com/{i}", title=f"Doc {i}", citation=f"[{i}]")
        for i in range(1, n + 1)
    ]


@pytest.mark.asyncio
async def test_citation_markers_map_to_real_passages():
    passages = _passages(3)
    model = FakeModel("Answer uses [1] and [3].")
    answer = await synthesize("q", passages, model)
    assert answer.passages == [passages[0], passages[2]]


@pytest.mark.asyncio
async def test_hallucinated_citation_is_dropped_not_passed_through():
    passages = _passages(2)
    model = FakeModel("Cites [1] and also [99], which does not exist.")
    answer = await synthesize("q", passages, model)
    assert answer.passages == [passages[0]]


@pytest.mark.asyncio
async def test_zero_passages_short_circuits_without_calling_the_model():
    calls = []

    class TrackingModel:
        async def complete(self, prompt: str) -> str:
            calls.append(prompt)
            return "should never run"

    answer = await synthesize("q", [], TrackingModel())
    assert answer.passages == []
    assert not calls, "zero passages should never reach the model"


@pytest.mark.asyncio
async def test_no_citations_at_all_yields_empty_used_passages():
    passages = _passages(2)
    model = FakeModel("A confident answer with no bracket markers.")
    answer = await synthesize("q", passages, model)
    assert answer.passages == []
    assert answer.text  # the text is still returned, just unverifiable


@pytest.mark.asyncio
async def test_retriever_answer_requires_a_model():
    r = Retriever(StaticSource(["http://127.0.0.1:1/x"]))
    with pytest.raises(RuntimeError, match="model"):
        await r.answer("q")


CORPUS = {
    "/asyncio": b"""<html><head><title>asyncio gather</title></head><body>
      <main>
        <h1>Running tasks concurrently</h1>
        <p>The gather function runs awaitables concurrently and returns their results.</p>
      </main>
    </body></html>""",
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = CORPUS.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
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


@pytest.mark.asyncio
async def test_retriever_answer_wires_search_into_synthesize(base_url):
    model = FakeModel("gather runs tasks concurrently [1].")
    async with Retriever(
        StaticSource([f"{base_url}/asyncio"]), model=model, allow_private=True
    ) as r:
        answer = await r.answer("gather concurrently")
    assert answer.passages
    assert answer.passages[0].url.endswith("/asyncio")


@pytest.mark.asyncio
async def test_default_search_is_unaffected_by_a_model_being_configured(base_url):
    model = FakeModel("unused")
    async with Retriever(
        StaticSource([f"{base_url}/asyncio"]), model=model, allow_private=True
    ) as r:
        result = await r.search("gather concurrently")
    assert result.passages  # search() still returns RetrievalResult, untouched


@pytest.mark.asyncio
async def test_hallucinated_citation_is_reported_not_just_dropped():
    """Dropping it from `passages` is not enough: `text` still contains the marker,
    so a caller rendering the prose would show a citation resolving to nothing."""
    passages = [Passage(text="real", url="https://a.example", title="A", citation="[0] x")]
    answer = await synthesize("q", passages, FakeModel("Grounded [1] but also [7]."))
    assert [p.url for p in answer.passages] == ["https://a.example"]
    assert answer.unresolved_citations == [7]
    assert answer.fully_grounded is False


@pytest.mark.asyncio
async def test_clean_answer_is_marked_fully_grounded():
    passages = [Passage(text="real", url="https://a.example", title="A", citation="[0] x")]
    answer = await synthesize("q", passages, FakeModel("All good [1]."))
    assert answer.unresolved_citations == []
    assert answer.fully_grounded is True
