from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from grip.compression.summarizer import Element, PageSnapshot


@dataclass
class SnapshotDelta:
    """What changed between two snapshots of the same document.

    Elements diff by ref (stable per handle), not by position, so inserting a
    banner at the top of the page is one addition rather than a wholesale
    renumbering. Content diffs by word run: a line diff would collapse the entire
    CONTENT block into one changed line the moment any text moved, which measured
    at 34% savings against 79% for word runs.
    """

    version: int
    previous_version: int
    added: list[Element] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[tuple[str, str, str]] = field(default_factory=list)
    content_ops: list[str] = field(default_factory=list)
    url_changed: bool = False

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed or self.content_ops)


def _content_ops(old: str, new: str) -> list[str]:
    if old == new:
        return []
    old_words = old.split()
    new_words = new.split()
    matcher = difflib.SequenceMatcher(a=old_words, b=new_words, autojunk=False)
    ops: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("replace", "insert"):
            ops.append(f"+{j1}: {' '.join(new_words[j1:j2])}")
        if tag in ("replace", "delete"):
            ops.append(f"-{i1}:{i2 - i1}")
    return ops


# Element handles are stamped by a per-window counter (gripStamp in
# grip/cdp/shadow.py), and that counter dies with the document. A click-driven
# navigation therefore restamps h1..hN on the *new* page, so two unrelated
# documents share almost every handle — and if the reported URL lags the DOM,
# build_delta's url guard sees "same page" and diffs them element for element.
# That is not just wasteful, it is misleading: it describes a page transition the
# model cannot reconstruct. (Measured on HN turn 6, benchmarks/RESULTS_AB.md.)
#
# Note the direction: a *same-document* SPA re-render keeps the window alive, so
# the counter keeps climbing and the new nodes get fresh handles — a wholesale
# DOM replacement has DISJOINT handles, not overlapping ones, and reads as a
# perfectly ordinary delta here.
#
# The shape this cannot separate from a restamp is in-place reconciliation: a
# keyed list patched by React/Vue retains the DOM nodes, so the handles survive
# while nearly every text changes. That looks exactly like a restamp from inside
# a snapshot. The ambiguity is resolved toward the snapshot deliberately —
# guessing "same document" there ships a diff between two unrelated pages, while
# guessing "new document" costs one turn of compression.
_MIN_SHARED_HANDLES = 4
_MIN_HANDLE_AGREEMENT = 0.5


def _is_restamped_document(previous: PageSnapshot, current: PageSnapshot) -> bool:
    """True when the two snapshots' shared handles describe different elements,
    which only happens when the handle counter restarted — a new document.

    Costs one pass over the element lists (no CDP round trip, nothing outside the
    snapshot that is already in hand). The error is asymmetric: a false positive
    costs one turn of compression, a false negative ships a diff between two
    unrelated pages, so the ratio errs toward flagging.
    """
    before = {el.handle: el for el in previous.elements if el.handle}
    after = {el.handle: el for el in current.elements if el.handle}
    shared = before.keys() & after.keys()
    # Below the floor the ratio is noise (one edited field on a two-field form
    # reads as 0% agreement), and such a page renders to a small snapshot anyway,
    # so the Layer 1 size check is enough there.
    if len(shared) < _MIN_SHARED_HANDLES:
        return False
    agreed = sum(
        1 for h in shared
        if (before[h].tag, before[h].role, before[h].text, before[h].placeholder)
        == (after[h].tag, after[h].role, after[h].text, after[h].placeholder)
    )
    # 0.5 rather than "any disagreement": within one document a handle's tag can
    # never change but its text can (a button relabels, a field fills in), and a
    # busy page can legitimately move several at once. Across a restamp the only
    # agreement is coincidence — the HN case that motivated this scored 0.04,
    # from a shared header — so anything under half is a different document.
    return agreed / len(shared) < _MIN_HANDLE_AGREEMENT


def build_delta(
    previous: PageSnapshot | None, current: PageSnapshot
) -> SnapshotDelta | None:
    """None means "no delta is meaningful, send the full snapshot" — either there
    is nothing to diff against, or the document itself changed."""
    if previous is None:
        return None
    if previous.url != current.url:
        return None
    # The url guard above is necessary but not sufficient: it trusts a URL read
    # from the same snapshot whose DOM may already have moved on.
    if _is_restamped_document(previous, current):
        return None

    before = {el.ref: el for el in previous.elements}
    after = {el.ref: el for el in current.elements}

    delta = SnapshotDelta(
        version=current.version, previous_version=previous.version
    )
    delta.added = [el for ref, el in after.items() if ref not in before]
    delta.removed = [ref for ref in before if ref not in after]
    delta.changed = [
        (ref, before[ref].text, after[ref].text)
        for ref in after
        if ref in before and before[ref].text != after[ref].text
    ]
    delta.content_ops = _content_ops(previous.text_content, current.text_content)
    return delta


_TAG_ABBREV = {"button": "btn", "input": "inp", "a": "lnk", "select": "sel",
               "textarea": "inp"}


def format_delta(delta: SnapshotDelta) -> str:
    if delta.is_empty:
        return f"DELTA v{delta.previous_version}->v{delta.version}: no change"
    lines = [f"DELTA v{delta.previous_version}->v{delta.version}"]
    for el in delta.added:
        abbrev = _TAG_ABBREV.get(el.tag, el.tag[:3])
        desc = el.text or el.placeholder or el.role
        lines.append(f"  + [{abbrev}:{el.ref}] {desc!r}")
    for ref in delta.removed:
        lines.append(f"  - [{ref}]")
    for ref, old, new in delta.changed:
        lines.append(f"  ~ [{ref}] {old!r} -> {new!r}")
    if delta.content_ops:
        lines.append("  CONTENT:")
        for op in delta.content_ops:
            lines.append(f"    {op}")
    return "\n".join(lines)


# A delta only exists to save tokens. One that does not save them has no reason
# to be sent, whatever went wrong upstream — so this is the backstop that holds
# even when a document-identity check misses.
_WORTHWHILE_RATIO = 0.9


def is_worth_sending(rendered_delta: str, rendered_snapshot: str) -> bool:
    """Compare rendered characters, not tokens: both strings come out of the same
    renderer, so characters track tokens closely, whereas a tiktoken pass over
    both strings on every turn is real work on the hot path for a check that only
    needs to catch gross regressions.

    At parity the snapshot wins outright — it is self-contained and re-anchors
    every ref — so the delta has to be meaningfully, not marginally, cheaper.
    """
    return len(rendered_delta) <= _WORTHWHILE_RATIO * len(rendered_snapshot)
