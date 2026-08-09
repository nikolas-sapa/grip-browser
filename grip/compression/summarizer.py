from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from grip.security.sanitizer import RawElement

if TYPE_CHECKING:
    from grip.errors.types import BrowserError

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")

    def _count_tokens(text: str) -> int:
        return len(_ENC.encode(text))
except Exception:  # noqa: BLE001 — tiktoken is optional; any failure to import or
    # fetch its encoding (missing package, no network for the cached vocab, etc.)
    # falls back to the char-count heuristic below rather than breaking snapshotting.
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
    tag: str
    role: str
    text: str
    placeholder: str | None
    in_shadow_dom: bool
    cx: int
    cy: int
    ref: str = ""
    handle: str = ""
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
    page_error: BrowserError | None = None
    # Detections used to be computed and discarded, so a caller had no way to tell
    # a stripped page from a clean one — which is the difference between "this page
    # is quiet" and "this page tried something and we cut it out".
    prompt_injection: bool = False

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
                tag=el.tag,
                role=el.role,
                text=el.text,
                placeholder=el.placeholder,
                in_shadow_dom=el.in_shadow_dom,
                cx=el.cx,
                cy=el.cy,
                handle=el.handle,
                href=el.href,
            )
            for i, el in enumerate(raw_elements)
        ]
        text_content = page_text.strip()
        # No token count here: page.py recomputes it after refs are assigned, and
        # this one was both discarded and wrong — it tokenized index-based refs.
        return PageSnapshot(
            version=version,
            url=url,
            title=title,
            elements=elements,
            text_content=text_content,
            tokens_estimated=0,
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
