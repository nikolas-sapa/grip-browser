from __future__ import annotations
import hashlib
from grip.compression.summarizer import Element


def _cache_key(tag: str, text: str) -> str:
    return hashlib.md5(f"{tag}:{text}".encode()).hexdigest()


class ElementCache:
    def __init__(self) -> None:
        self._store: dict[str, Element] = {}

    def store(self, element: Element) -> None:
        key = _cache_key(element.tag, element.text)
        self._store[key] = element

    def get(self, tag: str, text: str) -> Element | None:
        return self._store.get(_cache_key(tag, text))

    def invalidate(self) -> None:
        self._store.clear()

    def store_many(self, elements: list[Element]) -> None:
        for el in elements:
            self.store(el)
