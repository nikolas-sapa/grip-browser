from __future__ import annotations

import re

_REF_PATTERN = re.compile(r"^e(\d+)$")


class RefRegistry:
    """Stable, unique short names for elements.

    Keyed on the DOM handle rather than a hash of tag+text: two "Delete" buttons
    are two elements, and collapsing them onto one ref made the second
    unreachable and let a hidden decoy sharing a label absorb clicks meant for
    the visible control.
    """

    def __init__(self) -> None:
        self._handle_to_ref: dict[str, str] = {}
        self._next: int = 1

    def assign(self, handle: str) -> str:
        if handle not in self._handle_to_ref:
            self._handle_to_ref[handle] = f"e{self._next}"
            self._next += 1
        return self._handle_to_ref[handle]

    def evict(self, live_handles: set[str]) -> None:
        """Drop refs whose elements are gone, so a long session on one URL
        (infinite scroll, SPA) does not grow the map without bound."""
        self._handle_to_ref = {
            h: r for h, r in self._handle_to_ref.items() if h in live_handles
        }

    def reset(self) -> None:
        """Clear ref assignments for a new document.

        `_next` is deliberately NOT reset. Restarting numbering at e1 for every
        new document made a stale ref indistinguishable from a live one: an
        agent still holding "e3" from the page it just left would silently
        resolve against whatever the new document's third-assigned element
        happens to be — a different element, matched by coincidence of number
        rather than identity. Never reusing a ref number means a ref that
        belonged to a previous document simply never appears in the current
        map again, so it fails to match instead of matching the wrong thing.
        See Page._find_element/_find_input/_find_select and is_stale() below.
        """
        self._handle_to_ref.clear()

    def is_stale(self, ref: str) -> bool:
        """True if `ref` looks like a real ref this registry once issued (its
        number is below the next one to be handed out) but does not name any
        element live right now — either because it belonged to a document
        this page has since navigated away from (see reset(), above), or
        because its element was evicted from the current document. False for
        a description that was never a ref at all (an ordinary text match),
        which is a "not found", not "stale".
        """
        m = _REF_PATTERN.match(ref)
        if not m:
            return False
        return int(m.group(1)) < self._next and ref not in self._handle_to_ref.values()
