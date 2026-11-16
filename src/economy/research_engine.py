"""Multi-query coordinator for public research discovery leads.

This coordinates one configured provider; multiple queries do not equal
independent sources or verified demand.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

from .research_sources import GoogleNewsRSSProvider, ResearchCandidate


class ResearchDiscoveryEngine:
    def __init__(self, provider: GoogleNewsRSSProvider | None = None) -> None:
        self.provider = provider or GoogleNewsRSSProvider()

    def discover(self, queries: list[str], *, limit_per_query: int = 10) -> list[ResearchCandidate]:
        cleaned = [" ".join(q.split()) for q in queries]
        cleaned = [q for q in cleaned if q]
        if not cleaned:
            raise ValueError("at least one non-empty query is required")
        if len(cleaned) > 10:
            raise ValueError("a maximum of 10 queries is allowed")
        if not 1 <= limit_per_query <= 50:
            raise ValueError("limit_per_query must be between 1 and 50")
        by_url: dict[str, ResearchCandidate] = {}
        for query in dict.fromkeys(cleaned):
            for item in self.provider.search(query, limit=limit_per_query):
                # One record per original article URL across all queries.
                stable_id = sha256(item.article_url.encode("utf-8")).hexdigest()[:20]
                candidate = replace(item, candidate_id=stable_id)
                by_url.setdefault(item.article_url, candidate)
        return list(by_url.values())
