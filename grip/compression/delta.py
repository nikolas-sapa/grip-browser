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


def build_delta(
    previous: PageSnapshot | None, current: PageSnapshot
) -> SnapshotDelta | None:
    """None means "no delta is meaningful, send the full snapshot" — either there
    is nothing to diff against, or the document itself changed."""
    if previous is None:
        return None
    if previous.url != current.url:
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
