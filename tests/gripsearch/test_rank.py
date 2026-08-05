"""Ranking is a pure function over blocks — no browser needed."""
import pytest
from grip.reader import Block, Document

from gripsearch.fetch import Fetched
from gripsearch.rank import rank, _near_duplicate
from gripsearch.types import Candidate


def _doc(url, *texts, title="T"):
    blocks = [Block(id=i, kind="text", text=t, path=["Top"]) for i, t in enumerate(texts)]
    return Fetched(
        candidate=Candidate(url=url, title=title, rank=0),
        document=Document(title=title, url=url, blocks=blocks),
    )


def test_matching_block_outranks_unrelated_one():
    f = _doc("u", "the quick brown fox jumps over the lazy sleeping dog today",
                  "completely unrelated text about marine biology and coral reefs here")
    out = rank("quick brown fox", [f])
    assert out
    assert "quick brown fox" in out[0].text


def test_blocks_below_the_word_floor_are_skipped():
    """One-word blocks are navigation debris, not evidence."""
    f = _doc("u", "fox", "the quick brown fox jumps over the lazy sleeping dog today")
    out = rank("fox", [f], min_words=8)
    assert all(len(p.text.split()) >= 8 for p in out)


def test_headings_never_become_passages():
    doc = Document(title="T", url="u", blocks=[
        Block(id=0, kind="heading", text="A heading mentioning gather many times over", path=[]),
        Block(id=1, kind="text", text="Body text that also mentions gather and other words here", path=[]),
    ])
    out = rank("gather", [Fetched(candidate=Candidate(url="u"), document=doc)])
    assert all(p.text.startswith("Body") for p in out)


def test_source_rank_breaks_ties():
    a = _doc("a", "identical wording about gather appearing in both of these documents")
    b = _doc("b", "identical wording about gather appearing in both of these documents")
    b.candidate.rank = 5
    out = rank("gather", [a, b])
    assert out[0].url == "a"


def test_limit_is_respected():
    # Distinct wording per block: near-identical blocks would be collapsed by
    # dedup before the limit ever applied.
    topics = ["marine biology coral", "railway signalling systems", "baroque harpsichord tuning",
              "glacial moraine formation", "byzantine mosaic restoration", "tidal turbine design"]
    f = _doc("u", *[f"gather is discussed here alongside {t} in considerable detail" for t in topics])
    assert len(rank("gather", [f], limit=3)) == 3


def test_empty_query_returns_nothing():
    assert rank("", [_doc("u", "some text about things")]) == []


def test_no_match_returns_nothing():
    out = rank("zzzz", [_doc("u", "the quick brown fox jumps over the lazy dog today")])
    assert out == []


@pytest.mark.parametrize("a,b,expected", [
    ("the same sentence exactly", "the same sentence exactly", True),
    ("the same sentence exactly", "The Same Sentence Exactly", True),
    ("completely different words", "nothing alike whatsoever here", False),
])
def test_near_duplicate_detection(a, b, expected):
    assert _near_duplicate(a, b) is expected
