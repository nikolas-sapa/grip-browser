from __future__ import annotations
import hashlib
from grip.compression.summarizer import PageSnapshot


def _snapshot_fingerprint(snap: PageSnapshot) -> str:
    element_sig = "|".join(f"{el.tag}:{el.text}" for el in snap.elements)
    raw = f"{snap.url}||{snap.text_content[:500]}||{element_sig}"
    return hashlib.md5(raw.encode()).hexdigest()


class SnapshotDiff:
    def __init__(self) -> None:
        self._last_fingerprint: str | None = None

    def has_changed(self, snapshot: PageSnapshot) -> bool:
        fp = _snapshot_fingerprint(snapshot)
        return fp != self._last_fingerprint

    def record(self, snapshot: PageSnapshot) -> None:
        self._last_fingerprint = _snapshot_fingerprint(snapshot)
