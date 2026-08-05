"""Where candidate URLs come from.

One method, deliberately. grip has no business knowing that Brave exists, and the
pipeline has no business knowing which vendor is behind this.

There is no scrape-based implementation on purpose: measured, SERP scraping returns
zero extractable results on every engine tried, and an implementation that returns
nothing is worse than no implementation because it gets reached for during an outage.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Protocol, runtime_checkable

from gripsearch.types import Candidate


@runtime_checkable
class CandidateSource(Protocol):
    async def find(self, query: str, limit: int = 8) -> list[Candidate]:
        """Return up to `limit` candidates, best first."""
        ...


class BraveSource:
    """Brave Search API. $5 per 1000 queries at time of writing."""

    ENDPOINT = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, timeout: float = 10.0) -> None:
        if not api_key:
            raise ValueError("BraveSource needs an API key")
        self._api_key = api_key
        self._timeout = timeout

    async def find(self, query: str, limit: int = 8) -> list[Candidate]:
        import asyncio

        url = f"{self.ENDPOINT}?{urllib.parse.urlencode({'q': query, 'count': limit})}"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self._api_key,
            },
        )

        def _fetch() -> dict:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read())

        data = await asyncio.to_thread(_fetch)
        results = (data.get("web") or {}).get("results") or []
        return [
            Candidate(
                url=r["url"],
                title=r.get("title", ""),
                snippet=r.get("description", ""),
                rank=i,
            )
            for i, r in enumerate(results[:limit])
            if r.get("url")
        ]


class StaticSource:
    """Fixed candidates. For tests, and for 'search within these pages' callers."""

    def __init__(self, urls: list[str]) -> None:
        self._urls = urls

    async def find(self, query: str, limit: int = 8) -> list[Candidate]:
        return [Candidate(url=u, rank=i) for i, u in enumerate(self._urls[:limit])]
