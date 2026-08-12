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
except Exception:
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
    # Interaction state DISCOVER now captures alongside identity/position — an
    # agent deciding whether to click/type needs to know a control is already
    # disabled or filled before it acts, not after the action silently no-ops.
    disabled: bool = False
    required: bool = False
    checked: bool | None = None
    selected: bool | None = None
    value: str | None = None


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
    # Populated by page.py (Page.scroll()) after build(); flat, not a nested
    # class, per the contract agreed with the scroll() implementation. Default
    # 0/0 for callers/tests that predate scroll() and never set these — the
    # renderer treats scroll_height <= 0 as "not populated" and omits the
    # VIEWPORT line rather than print a meaningless y=0/0.
    scroll_top: int = 0
    scroll_left: int = 0
    scroll_height: int = 0
    client_height: int = 0

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
                # getattr, not el.disabled: RawElement (grip/security/sanitizer.py)
                # does not carry these fields yet — DISCOVER_ELEMENTS_JS
                # (grip/cdp/shadow.py) already emits disabled/required/checked/
                # selected/value, but page.py's RawElement(...) construction has
                # to be extended to read and forward them before this stops
                # silently defaulting. Field names here are the proposed contract.
                disabled=getattr(el, "disabled", False),
                required=getattr(el, "required", False),
                checked=getattr(el, "checked", None),
                selected=getattr(el, "selected", None),
                value=getattr(el, "value", None),
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
        # Leading, not buried in CONTENT: an agent that only reads the top of a
        # long snapshot must still see that the page errored or was tampered
        # with before it reasons about anything below.
        leading: list[str] = []
        if snapshot.page_error is not None:
            leading.append(self._format_status_line(snapshot.page_error))
        if snapshot.prompt_injection:
            leading.append(
                "WARNING: this page attempted a prompt injection; the "
                "offending text was elided before this snapshot was built."
            )
        body = self._build_format_str(
            snapshot.url,
            snapshot.title,
            snapshot.elements,
            snapshot.text_content,
            snapshot.scroll_top,
            snapshot.scroll_left,
            snapshot.scroll_height,
        )
        return "\n".join([*leading, body]) if leading else body

    def count_tokens(self, text: str) -> int:
        return _count_tokens(text)

    @staticmethod
    def _format_status_line(error: BrowserError) -> str:
        recovery = ", ".join(action.value for action in error.recovery)
        suffix = f" (recovery: {recovery})" if recovery else ""
        return f"STATUS: {error.type.value}{suffix}"

    @staticmethod
    def _format_viewport_line(scroll_top: int, scroll_left: int, scroll_height: int) -> str:
        # scroll_height <= 0 means this snapshot predates Page.scroll()
        # populating these fields (an older caller, or a directly-built
        # PageSnapshot in a test) — there is nothing real to report, so the
        # line is omitted rather than printing a meaningless "y=0/0".
        if scroll_height <= 0:
            return ""
        line = f"VIEWPORT: y={scroll_top}/{scroll_height}"
        # Horizontal scroll is rare enough that reporting it unconditionally
        # would cost a token on every snapshot for no benefit on the common
        # vertically-scrolling page — only shown when it is actually nonzero.
        if scroll_left:
            line += f" x={scroll_left}"
        return line

    @staticmethod
    def _element_state_suffix(el: Element) -> str:
        # Only positive/active state is rendered — "unchecked"/"enabled" on
        # every ordinary control would double INTERACTIVE's line count for no
        # information the absence of "(checked)"/"(disabled)" doesn't already
        # carry, and this line format is explicitly token-budget-constrained.
        suffix = f' ="{el.value}"' if el.value else ""
        flags = [
            name
            for name, active in (
                ("disabled", el.disabled),
                ("required", el.required),
                ("checked", el.checked),
                ("selected", el.selected),
            )
            if active
        ]
        if flags:
            suffix += " (" + ", ".join(flags) + ")"
        return suffix

    def _build_format_str(
        self,
        url: str,
        title: str,
        elements: list[Element],
        text: str,
        scroll_top: int,
        scroll_left: int,
        scroll_height: int,
    ) -> str:
        lines = [f"PAGE: {title}", f"URL: {url}"]
        viewport = self._format_viewport_line(scroll_top, scroll_left, scroll_height)
        if viewport:
            lines.append(viewport)
        if elements:
            lines.append("INTERACTIVE:")
            for el in elements:
                abbrev = _TAG_ABBREV.get(el.tag, el.tag[:3])
                desc = el.text or el.placeholder or el.role
                ref = el.ref or str(el.index)
                lines.append(
                    f"  [{abbrev}:{ref}] {desc!r}{self._element_state_suffix(el)}"
                )
        if text:
            lines.append("CONTENT:")
            lines.append(f"  {text[:2000]}")
            if len(text) > 2000:
                lines.append(
                    f"  ... [{len(text) - 2000} more characters truncated — call "
                    "read() for the full content]"
                )
        return "\n".join(lines)
