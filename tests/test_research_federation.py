import unittest

from economy.research_federation import MultiSourceResearch
from economy.research_sources import ResearchCandidate


class FakeSource:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def search(self, query, *, limit):
        self.calls.append((query, limit))
        return [ResearchCandidate(
            candidate_id=self.name,
            query=query,
            title=f"{self.name} result",
            article_url=f"https://{self.name}.example/item",
            publisher=self.name,
            published_at="",
            discovered_at="2026-11-16T00:00:00+00:00",
            source_kind=f"{self.name}_lead",
        )]


class MultiSourceResearchTests(unittest.TestCase):
    def test_queries_both_providers_and_preserves_provenance(self):
        news = FakeSource("news")
        community = FakeSource("community")
        results = MultiSourceResearch(news=news, community=community).discover("  product idea  ", limit=4)
        self.assertEqual(len(results), 2)
        self.assertEqual(news.calls, [("product idea", 4)])
        self.assertEqual(community.calls, [("product idea", 4)])
        self.assertEqual([r.source_kind for r in results], ["news_lead", "community_lead"])
        self.assertEqual([r.candidate_id for r in results], ["news", "community"])

    def test_rejects_invalid_query_and_limit_before_fetching(self):
        news = FakeSource("news")
        community = FakeSource("community")
        service = MultiSourceResearch(news=news, community=community)
        with self.assertRaises(ValueError):
            service.discover(" ")
        with self.assertRaises(ValueError):
            service.discover("query", limit=51)
        self.assertEqual(news.calls, [])
        self.assertEqual(community.calls, [])


if __name__ == "__main__":
    unittest.main()
