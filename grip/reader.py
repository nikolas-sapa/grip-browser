"""Read mode — a page as a reader sees it, not as an actor does.

`Page.snapshot()` answers "what can I click here". This answers "what does this
page say", which is a different question with a different shape: prose instead of
controls, ordered blocks instead of an element index, and a citable location for
every claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Block:
    """One citable unit of a page.

    `id` plus `path` is the citation: the block's position in reading order, and
    the heading trail above it. The trail survives a re-fetch that shifts offsets,
    which a character index does not.
    """

    id: int
    kind: str          # "heading" | "text" | "code"
    text: str
    path: list[str] = field(default_factory=list)
    level: int = 0     # heading depth, 0 for body blocks

    @property
    def citation(self) -> str:
        where = " › ".join(self.path) if self.path else "(top)"  # noqa: RUF001
        return f"[{self.id}] {where}"


@dataclass
class Document:
    title: str
    url: str
    blocks: list[Block]

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)

    @property
    def headings(self) -> list[Block]:
        return [b for b in self.blocks if b.kind == "heading"]

    def outline(self) -> str:
        """Cheap map of the page — useful for deciding whether to read it at all."""
        return "\n".join(f"{'  ' * (b.level - 1)}{b.text}" for b in self.headings)

    def __len__(self) -> int:
        return len(self.blocks)
