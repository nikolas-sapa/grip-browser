from __future__ import annotations
import hashlib


def _fingerprint(tag: str, text: str) -> str:
    return hashlib.md5(f"{tag}:{text}".encode()).hexdigest()


class RefRegistry:
    def __init__(self) -> None:
        self._fp_to_ref: dict[str, str] = {}
        self._next: int = 1

    def assign(self, tag: str, text: str) -> str:
        fp = _fingerprint(tag, text)
        if fp not in self._fp_to_ref:
            self._fp_to_ref[fp] = f"e{self._next}"
            self._next += 1
        return self._fp_to_ref[fp]

    def reset(self) -> None:
        self._fp_to_ref.clear()
        self._next = 1
