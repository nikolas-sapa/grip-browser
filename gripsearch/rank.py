"""Rank and dedup blocks across documents.

BM25 over blocks, with the discovery source's own ranking as a prior. Deliberately
not embeddings: they add a model call and an index to a pipeline whose cost is
already dominated by the LLM read, and nothing measured says lexical ranking is the
accuracy bottleneck. Revisit when a reach evaluation exists.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from gripsearch.fetch import Fetched
from gripsearch.types import Passage
from grip.reader import Block

_WORD = re.compile(r"[a-z0-9]+")

K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _trigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", " ", text.lower()).strip()
    return {t[i : i + 3] for i in range(max(len(t) - 2, 0))}


def _near_duplicate(a: str, b: str, threshold: float = 0.9) -> bool:
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / min(len(ta), len(tb))
    return overlap >= threshold


def rank(
    query: str,
    fetched: list[Fetched],
    limit: int = 12,
    min_words: int = 8,
) -> list[Passage]:
    """Score every block against the query, drop duplicates, return the best."""
    q_terms = tokenize(query)
    if not q_terms:
        return []

    # Flatten to (fetched, block) and keep only prose worth citing. Headings are
    # navigation, not evidence — they already ride along in each block's path.
    items = [
        (f, b)
        for f in fetched
        for b in f.document.blocks
        if b.kind != "heading" and len(tokenize(b.text)) >= min_words
    ]
    if not items:
        return []

    docs = [tokenize(b.text) for _, b in items]
    avg_len = sum(len(d) for d in docs) / len(docs)
    n = len(docs)

    df: Counter[str] = Counter()
    for d in docs:
        for term in set(d):
            df[term] += 1

    scored: list[tuple[float, Fetched, Block]] = []
    for (f, block), terms in zip(items, docs):
        tf = Counter(terms)
        score = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            freq = tf[term]
            score += idf * (freq * (K1 + 1)) / (
                freq + K1 * (1 - B + B * len(terms) / avg_len)
            )
        if score <= 0:
            continue
        # Discovery already ranked the sources; let that break ties without
        # letting it override a clearly better passage further down the list.
        score *= 1.0 / (1.0 + 0.1 * f.candidate.rank)
        scored.append((score, f, block))

    scored.sort(key=lambda x: x[0], reverse=True)

    passages: list[Passage] = []
    for score, f, block in scored:
        if any(_near_duplicate(block.text, p.text) for p in passages):
            continue
        passages.append(
            Passage(
                text=block.text,
                url=f.document.url or f.candidate.url,
                title=f.candidate.title or f.document.title,
                citation=block.citation,
                score=round(score, 4),
            )
        )
        if len(passages) >= limit:
            break
    return passages
