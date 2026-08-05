"""Drive grip against candidate URLs, concurrently.

Owns the concurrency pool: grip deliberately ships no limit, and the safe ceiling
is machine-dependent (measured ~219 MB per live tab).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from graft.types import Candidate, SourceFailure
from grip.browser import Browser
from grip.reader import Document

logger = logging.getLogger(__name__)


@dataclass
class Fetched:
    candidate: Candidate
    document: Document


async def fetch_all(
    browser: Browser,
    candidates: list[Candidate],
    per_page_timeout: float = 15.0,
    max_concurrent: int = 8,
) -> tuple[list[Fetched], list[SourceFailure]]:
    """Fetch every candidate. Returns what worked and what did not — a source that
    failed is reported, never silently dropped."""
    sem = asyncio.Semaphore(max_concurrent)
    ok: list[Fetched] = []
    failed: list[SourceFailure] = []

    async def one(candidate: Candidate) -> None:
        async with sem:
            page = None
            try:
                page = await asyncio.wait_for(
                    browser.open(candidate.url), timeout=per_page_timeout
                )
                snap = await page.snapshot()
                # Cheapest possible filter: drop a blocked page before spending a
                # single token reading it.
                if snap.page_error is not None:
                    failed.append(
                        SourceFailure(candidate.url, snap.page_error.type)
                    )
                    return
                doc = await page.read()
                if not doc.blocks:
                    failed.append(SourceFailure(candidate.url, "no_content"))
                    return
                if not candidate.title:
                    candidate.title = doc.title
                ok.append(Fetched(candidate=candidate, document=doc))
            except TimeoutError:
                failed.append(SourceFailure(candidate.url, "timeout"))
            except Exception as e:
                logger.debug("fetch failed for %s", candidate.url, exc_info=True)
                failed.append(SourceFailure(candidate.url, type(e).__name__))
            finally:
                if page is not None:
                    try:
                        await page.close()
                    except Exception:
                        logger.debug("close failed for %s", candidate.url, exc_info=True)

    await asyncio.gather(*(one(c) for c in candidates))
    # gather() completion order is nondeterministic; restore the source's ranking
    ok.sort(key=lambda f: f.candidate.rank)
    return ok, failed
