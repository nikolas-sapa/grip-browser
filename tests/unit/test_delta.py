from __future__ import annotations

from dataclasses import fields
from typing import Any

from grip.compression.delta import build_delta, format_delta, is_worth_sending
from grip.compression.summarizer import Element, PageSnapshot

# `Element.handle` arrives with the Phase 1 handle work, which is being written
# in parallel with this file. Reading the dataclass's own field list keeps these
# tests green in either landing order instead of pinning them to one.
_ELEMENT_FIELDS = {f.name for f in fields(Element)}


def _el(ref: str, handle: str, text: str, tag: str = "button") -> Element:
    kwargs: dict[str, Any] = {
        "index": 0, "tag": tag, "role": tag, "text": text,
        "placeholder": None, "in_shadow_dom": False, "cx": 0, "cy": 0, "ref": ref,
    }
    if "handle" in _ELEMENT_FIELDS:
        kwargs["handle"] = handle
    return Element(**kwargs)


def _snap(version: int, elements: list[Element], content: str,
          url: str = "https://x.test") -> PageSnapshot:
    return PageSnapshot(
        version=version, url=url, title="t", elements=elements,
        text_content=content, tokens_estimated=0,
    )


def test_no_previous_snapshot_yields_none():
    assert build_delta(None, _snap(1, [], "hello")) is None


def test_url_change_yields_none():
    a = _snap(1, [], "hello", url="https://a.test")
    b = _snap(2, [], "hello", url="https://b.test")
    assert build_delta(a, b) is None


def test_identical_snapshots_produce_empty_delta():
    els = [_el("e1", "h0", "Buy")]
    d = build_delta(_snap(1, els, "same text"), _snap(2, list(els), "same text"))
    assert d is not None and d.is_empty


def test_elements_diff_by_key_not_by_index():
    before = [_el("e1", "h0", "Alpha"), _el("e2", "h1", "Beta")]
    after = [_el("e3", "h2", "Zulu"), _el("e1", "h0", "Alpha")]
    d = build_delta(_snap(1, before, ""), _snap(2, after, ""))
    assert [e.ref for e in d.added] == ["e3"]
    assert d.removed == ["e2"]
    assert d.changed == []


def test_changed_element_text_is_reported_once():
    d = build_delta(
        _snap(1, [_el("e1", "h0", "Add to cart")], ""),
        _snap(2, [_el("e1", "h0", "Remove from cart")], ""),
    )
    assert d.changed == [("e1", "Add to cart", "Remove from cart")]
    assert d.added == [] and d.removed == []


def test_content_diff_is_word_level_not_line_level():
    """One changed word in a long paragraph must not re-send the paragraph."""
    base = " ".join(f"word{i}" for i in range(400))
    changed = base.replace("word200", "REPLACED")
    d = build_delta(_snap(1, [], base), _snap(2, [], changed))
    rendered = format_delta(d)
    assert "REPLACED" in rendered
    assert len(rendered) < len(changed) / 4, "content diff re-sent most of the text"


def test_content_append_sends_only_the_tail():
    base = " ".join(f"word{i}" for i in range(300))
    d = build_delta(_snap(1, [], base), _snap(2, [], base + " brand new tail"))
    rendered = format_delta(d)
    assert "brand new tail" in rendered
    assert "word150" not in rendered, "unchanged prefix was re-sent"


def test_format_delta_is_compact_for_a_counter_bump():
    d = build_delta(_snap(1, [], "count: 3"), _snap(2, [], "count: 4"))
    assert len(format_delta(d)) < 80


def _restamped_pair(shared_header: int, body: int):
    """Two unrelated documents as the browser actually presents them: gripStamp's
    handle counter dies with the document, so the second page restamps h1..hN and
    the handles overlap completely even though nothing else does. Only the site
    header survives verbatim — this is the Hacker News news->newcomments shape
    from benchmarks/RESULTS_AB.md, which the URL guard missed because
    Target.getTargetInfo still reported the old URL."""
    header = [_el(f"e{i}", f"h{i}", f"nav{i}", tag="a") for i in range(shared_header)]
    before = header + [
        _el(f"e{shared_header + i}", f"h{shared_header + i}", f"Story {i}", tag="a")
        for i in range(body)
    ]
    after = header + [
        _el(f"e{shared_header + i}", f"h{shared_header + i}", f"Comment {i}", tag="a")
        for i in range(body)
    ]
    return (
        _snap(1, before, "front page stories about rust and compilers"),
        _snap(2, after, "newest comments from people arguing about licences"),
    )


def test_unrelated_document_with_restamped_handles_is_not_diffed():
    """The killer case: same reported URL, same handles, different document. A
    delta here is not merely expensive, it describes a transition the model
    cannot reconstruct."""
    before, after = _restamped_pair(shared_header=8, body=192)
    assert build_delta(before, after) is None


def test_an_edit_that_moves_most_elements_still_diffs():
    """Guard the win: a busy same-document turn changes several elements at once
    and must not be mistaken for a navigation."""
    before, after = _restamped_pair(shared_header=180, body=20)
    d = build_delta(before, after)
    assert d is not None and len(d.changed) == 20


def test_a_wholesale_spa_rerender_still_diffs():
    """An SPA replacing its DOM keeps the window alive, so the handle counter
    keeps climbing and the new nodes get fresh handles. Disjoint handles are the
    signature of a same-document replacement, not of a navigation."""
    before = [_el(f"e{i}", f"h{i}", f"row {i}") for i in range(20)]
    after = [_el(f"e{100 + i}", f"h{100 + i}", f"result {i}") for i in range(20)]
    d = build_delta(_snap(1, before, "old"), _snap(2, after, "new"))
    assert d is not None
    assert len(d.added) == 20 and len(d.removed) == 20


def test_handleless_elements_do_not_read_as_a_new_document():
    """Element.handle defaults to "": keying on it blindly would collapse every
    element onto one bucket and flag every page as a navigation."""
    before = [_el(f"e{i}", "", f"a{i}") for i in range(10)]
    after = [_el(f"e{i}", "", f"b{i}") for i in range(10)]
    assert build_delta(_snap(1, before, ""), _snap(2, after, "")) is not None


def test_a_delta_bigger_than_its_snapshot_is_not_worth_sending():
    assert not is_worth_sending("x" * 200, "y" * 100)


def test_a_delta_barely_smaller_than_its_snapshot_is_not_worth_sending():
    """At parity the snapshot wins outright: it is self-contained and re-anchors
    every ref, so a delta has to be meaningfully cheaper to earn its place."""
    assert not is_worth_sending("x" * 95, "y" * 100)
    assert is_worth_sending("x" * 40, "y" * 100)
