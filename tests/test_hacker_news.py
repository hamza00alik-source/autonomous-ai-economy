import json
import unittest
from urllib.parse import urlparse

from economy.hacker_news import HackerNewsSearchProvider


PAYLOAD = {
    "hits": [
        {
            "objectID": "12345",
            "title": "Ask HN: How do you manage invoices?",
            "url": "https://example.org/invoice-tool",
            "author": "founder",
            "points": 42,
            "num_comments": 17,
            "created_at": "2026-11-16T12:00:00Z",
        },
        {"objectID": "not-a-number", "title": "Invalid item"},
        {"objectID": "12346", "title": ""},
    ]
}


class HackerNewsProviderTests(unittest.TestCase):
    def test_parses_public_discussions_as_unverified_leads(self):
        provider = HackerNewsSearchProvider()
        seen = {}

        def fetch(url, timeout):
            seen["url"] = url
            seen["timeout"] = timeout
            return json.dumps(PAYLOAD).encode()

        provider._fetch = fetch
        results = provider.search("invoice workflow", limit=5)
        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item.title, "Ask HN: How do you manage invoices?")
        self.assertEqual(item.article_url, "https://news.ycombinator.com/item?id=12345")
        self.assertEqual(item.external_url, "https://example.org/invoice-tool")
        self.assertEqual(item.points, 42)
        self.assertEqual(item.comments, 17)
        self.assertEqual(item.author, "founder")
        self.assertEqual(item.source_kind, "community_discussion_lead")
        self.assertFalse(item.sales_verified)
        self.assertEqual(urlparse(seen["url"]).hostname, "hn.algolia.com")

    def test_query_and_limit_validation(self):
        provider = HackerNewsSearchProvider()
        with self.assertRaises(ValueError):
            provider.search(" ")
        with self.assertRaises(ValueError):
            provider.search("query", limit=0)
        with self.assertRaises(ValueError):
            provider.search("x" * 301)

    def test_network_fetch_rejects_unapproved_host_and_scheme(self):
        with self.assertRaises(ValueError):
            HackerNewsSearchProvider._fetch("http://hn.algolia.com/api/v1/search", 1)
        with self.assertRaises(ValueError):
            HackerNewsSearchProvider._fetch("https://example.org/api", 1)

    def test_response_body_limit(self):
        provider = HackerNewsSearchProvider()
        provider._fetch = lambda *_: b"x" * 1_000_001
        with self.assertRaises(ValueError):
            provider.search("query")


if __name__ == "__main__":
    unittest.main()
