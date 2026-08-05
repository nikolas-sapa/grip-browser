from __future__ import annotations

from dataclasses import dataclass, field

from grip.errors.types import ErrorType


@dataclass
class Candidate:
    """A URL worth fetching, as proposed by a discovery source."""

    url: str
    title: str = ""
    snippet: str = ""
    rank: int = 0  # position in the source's own ordering, 0 = best


@dataclass
class Passage:
    """A ranked block of text with enough provenance to cite it."""

    text: str
    url: str
    title: str
    citation: str  # e.g. "[12] Coroutines and tasks › Coroutines"
    score: float = 0.0

    def __str__(self) -> str:
        return f"{self.text}\n  — {self.url} {self.citation}"


@dataclass
class SourceFailure:
    """A source that was tried and could not be used. Never silently dropped."""

    url: str
    reason: ErrorType | str

    def __str__(self) -> str:
        reason = self.reason.value if isinstance(self.reason, ErrorType) else self.reason
        return f"{self.url}: {reason}"


@dataclass
class RetrievalResult:
    query: str
    passages: list[Passage] = field(default_factory=list)
    failures: list[SourceFailure] = field(default_factory=list)
    sources_consulted: int = 0
    elapsed_s: float = 0.0
    tokens_estimated: int = 0

    @property
    def text(self) -> str:
        return "\n\n".join(str(p) for p in self.passages)
