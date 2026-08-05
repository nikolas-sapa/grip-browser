"""Turn ranked passages into a cited answer, on request only.

Deliberately not grip's `LLMAdapter`: that protocol exists for tool-calling
inside an autonomous browser loop (`browser.run()`) and carries a `tools` list
and `ToolCall` outputs to match. Synthesis here is single-shot text in, text
out — dragging the tool-calling shape along would describe a need this does
not have.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from gripsearch.types import Passage

_CITATION = re.compile(r"\[(\d+)\]")


@runtime_checkable
class SynthesisModel(Protocol):
    async def complete(self, prompt: str) -> str:
        """Return the raw completion text for a single prompt."""
        ...


@dataclass
class Answer:
    """A synthesized answer plus the passages it actually cited.

    `passages` is filtered to entries a `[n]` marker in `text` really points
    to — never trusted from the model output as-is. That is what makes an
    `Answer` checkable: walk `passages`, not the prose, to verify a claim.
    """

    text: str
    passages: list[Passage] = field(default_factory=list)
    unresolved_citations: list[int] = field(default_factory=list)
    """Markers the model emitted that point at no real passage.

    `text` is returned unedited, so a hallucinated `[7]` stays in the prose while
    `passages` correctly excludes it — a caller rendering the prose would show a
    citation that resolves to nothing. Everywhere else in this package a failure is
    reported rather than dropped (SourceFailure, NoUsableSources, page_error); this
    is that same contract for citations. Non-empty means do not trust the prose.
    """

    @property
    def fully_grounded(self) -> bool:
        """Every citation the model made resolves to a real passage."""
        return not self.unresolved_citations


def _build_prompt(query: str, passages: list[Passage]) -> str:
    numbered = "\n\n".join(
        f"[{i}] {p.text}\n(source: {p.url})" for i, p in enumerate(passages, start=1)
    )
    return (
        "Answer the question using only the numbered sources below. Cite every "
        "claim with its source number in brackets, e.g. [1]. If the sources do "
        "not answer the question, say so.\n\n"
        f"Question: {query}\n\nSources:\n{numbered}\n\nAnswer:"
    )


async def synthesize(query: str, passages: list[Passage], model: SynthesisModel) -> Answer:
    """Ask `model` for an answer over `passages`, then hold it to its citations.

    No passages, no model call — an answer synthesized from nothing is not a
    degenerate case worth a round trip. A citation marker that does not
    resolve to a real passage (out of range, or no markers at all) is simply
    excluded from `passages` rather than trusted: a hallucinated `[7]` is
    worse than an answer that admits fewer citations than it claims.
    """
    if not passages:
        return Answer(text="No passages to answer from.", passages=[])

    raw = await model.complete(_build_prompt(query, passages))
    cited = {int(m) for m in _CITATION.findall(raw)}
    used = [passages[i - 1] for i in sorted(cited) if 1 <= i <= len(passages)]
    unresolved = sorted(i for i in cited if not 1 <= i <= len(passages))
    return Answer(text=raw, passages=used, unresolved_citations=unresolved)
