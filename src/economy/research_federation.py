"""Coordinates distinct free discovery providers without merging provenance."""
from __future__ import annotations

from .hacker_news import HackerNewsSearchProvider
from .research_sources import GoogleNewsRSSProvider, ResearchCandidate


class MultiSourceResearch:
    """Run separate discovery adapters and retain source-specific candidate IDs.

    Results from different platforms remain separate records. Their presence
    together is not proof of independent corroboration or buyer demand.
    """

    def __init__(
        self,
        *,
        news: GoogleNewsRSSProvider | None = None,
        community: HackerNewsSearchProvider | None = None,
    ) -> None:
        self.news = news or GoogleNewsRSSProvider()
        self.community = community or HackerNewsSearchProvider()

    def discover(self, query: str, *, limit: int = 10) -> list[ResearchCandidate]:
        cleaned = " ".join(query.split())
        if not cleaned:
            raise ValueError("query is required")
        if len(cleaned) > 300:
            raise ValueError("query must be 300 characters or fewer")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")

        # Preserve provider provenance; do not merge similar headlines or URLs.
        return [
            *self.news.search(cleaned, limit=limit),
            *self.community.search(cleaned, limit=limit),
        ]
