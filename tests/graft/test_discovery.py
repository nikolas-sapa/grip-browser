"""Contract every CandidateSource must satisfy."""
import pytest
from graft.discovery import BraveSource, CandidateSource, StaticSource


def test_static_source_satisfies_the_protocol():
    assert isinstance(StaticSource([]), CandidateSource)


def test_brave_source_satisfies_the_protocol():
    assert isinstance(BraveSource(api_key="x"), CandidateSource)


def test_brave_source_refuses_an_empty_key():
    with pytest.raises(ValueError, match="API key"):
        BraveSource(api_key="")


@pytest.mark.asyncio
async def test_source_respects_the_limit():
    src = StaticSource([f"https://example.com/{i}" for i in range(20)])
    assert len(await src.find("q", limit=3)) == 3


@pytest.mark.asyncio
async def test_candidates_carry_their_source_ordering():
    src = StaticSource(["https://a.example", "https://b.example"])
    got = await src.find("q")
    assert [c.rank for c in got] == [0, 1]
