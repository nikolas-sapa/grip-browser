from __future__ import annotations


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
        self._handle_to_ref.clear()
        self._next = 1
