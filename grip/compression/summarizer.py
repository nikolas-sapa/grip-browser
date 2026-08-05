from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from grip.security.sanitizer import RawElement

if TYPE_CHECKING:
    from grip.errors.types import BrowserError

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(text: str) -> int:
        return len(_ENC.encode(text))
except Exception:
    def _count_tokens(text: str) -> int:
        return len(text) // 4


_TAG_ABBREV = {
    "button": "btn",
    "input": "inp",
    "a": "lnk",
    "select": "sel",
    "textarea": "inp",
}


@dataclass
class Element:
    index: int
    snapshot_version: int
    tag: str
    role: str
    text: str
    placeholder: str | None
    in_shadow_dom: bool
    cx: int
    cy: int
    ref: str = ""
    href: str | None = None


@dataclass
class PageSnapshot:
    version: int
    url: str
    title: str
    elements: list[Element]
    text_content: str
    tokens_estimated: int
    changed_from_previous: bool = True
    page_error: "BrowserError | None" = None

    @property
    def links(self) -> list[tuple[str, str]]:
        """(text, absolute url) for every fetchable link. Hrefs stay out of the
        formatted snapshot — a results page carries ~34 of them, which would swamp
        the token budget — so this is how callers get at them."""
        return [(el.text, el.href) for el in self.elements if el.href]


class Summarizer:
    def build(
        self,
        version: int,
        url: str,
        title: str,
        raw_elements: list[RawElement],
        page_text: str,
    ) -> PageSnapshot:
        elements = [
            Element(
                index=i,
                snapshot_version=version,
                tag=el.tag,
                role=el.role,
                text=el.text,
                placeholder=el.placeholder,
                in_shadow_dom=el.in_shadow_dom,
                cx=el.cx,
                cy=el.cy,
                href=el.href,
            )
            for i, el in enumerate(raw_elements)
        ]
        text_content = page_text.strip()
        formatted = self._build_format_str(url, title, elements, text_content)
        tokens = _count_tokens(formatted)
        return PageSnapshot(
            version=version,
            url=url,
            title=title,
            elements=elements,
            text_content=text_content,
            tokens_estimated=tokens,
        )

    def format(self, snapshot: PageSnapshot) -> str:
        return self._build_format_str(
            snapshot.url, snapshot.title, snapshot.elements, snapshot.text_content
        )

    def count_tokens(self, text: str) -> int:
        return _count_tokens(text)

    def _build_format_str(
        self, url: str, title: str, elements: list[Element], text: str
    ) -> str:
        lines = [f"PAGE: {title}", f"URL: {url}"]
        if elements:
            lines.append("INTERACTIVE:")
            for el in elements:
                abbrev = _TAG_ABBREV.get(el.tag, el.tag[:3])
                desc = el.text or el.placeholder or el.role
                ref = el.ref or str(el.index)
                lines.append(f"  [{abbrev}:{ref}] {desc!r}")
        if text:
            lines.append("CONTENT:")
            lines.append(f"  {text[:2000]}")
        return "\n".join(lines)
