"""The façade: a question in, ranked cited passages out."""
from __future__ import annotations

import time
from typing import Self

from gripsearch.discovery import CandidateSource
from gripsearch.fetch import fetch_all
from gripsearch.rank import rank
from gripsearch.types import RetrievalResult
from grip.browser import Browser


class NoUsableSources(RuntimeError):
    """Every candidate failed. The failures are attached rather than swallowed."""

    def __init__(self, query: str, failures: list) -> None:
        self.query = query
        self.failures = failures
        detail = "; ".join(str(f) for f in failures) or "no candidates found"
        super().__init__(f"no usable sources for {query!r}: {detail}")


class Retriever:
    """
    Budgets default to the measured figures behind this design: 8 sources, 15s per
    page, 30s per query. Concurrency is capped because grip ships no limit and a
    live tab costs ~219 MB.
    """

    def __init__(
        self,
        source: CandidateSource,
        sources_per_query: int = 8,
        per_page_timeout: float = 15.0,
        max_concurrent: int = 8,
        passages: int = 12,
        headless: bool = True,
        stealth: bool = True,
    ) -> None:
        self._source = source
        self._n = sources_per_query
        self._per_page_timeout = per_page_timeout
        self._max_concurrent = max_concurrent
        self._passages = passages
        # stealth defaults ON here, unlike grip: a retrieval layer fetching public
        # pages has no reason to announce itself as automation, whereas a general
        # SDK does.
        self._headless = headless
        self._stealth = stealth
        self._browser: Browser | None = None

    async def __aenter__(self) -> Self:
        self._browser = Browser(headless=self._headless, stealth=self._stealth)
        await self._browser.__aenter__()
        return self

    async def __aexit__(self, *args) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None

    async def search(self, query: str) -> RetrievalResult:
        if self._browser is None:
            raise RuntimeError("use `async with Retriever(...)` before searching")

        t0 = time.monotonic()
        candidates = await self._source.find(query, limit=self._n)
        fetched, failures = await fetch_all(
            self._browser,
            candidates,
            per_page_timeout=self._per_page_timeout,
            max_concurrent=self._max_concurrent,
        )
        if not fetched:
            raise NoUsableSources(query, failures)

        passages = rank(query, fetched, limit=self._passages)
        result = RetrievalResult(
            query=query,
            passages=passages,
            failures=failures,
            sources_consulted=len(fetched),
            elapsed_s=round(time.monotonic() - t0, 2),
        )
        result.tokens_estimated = sum(len(p.text) for p in passages) // 4
        return result
