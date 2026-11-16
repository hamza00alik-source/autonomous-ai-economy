import unittest
from urllib.parse import urlparse

from economy.research_sources import GoogleNewsRSSProvider


RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>Example demand trend</title><link>https://publisher.example/article</link>
<pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate><source url="https://publisher.example">Publisher</source></item>
<item><title>Missing link</title><pubDate>Mon, 16 Nov 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


class ResearchSourceTests(unittest.TestCase):
    def test_parses_candidates_as_unverified_leads(self):
        seen = {}
        def fetch(url, timeout):
            seen["url"] = url
            seen["timeout"] = timeout
            return RSS

        candidates = GoogleNewsRSSProvider(fetcher=fetch).search("digital product demand", limit=5)
        self.assertEqual(len(candidates), 1)
        item = candidates[0]
        self.assertEqual(item.title, "Example demand trend")
        self.assertEqual(item.publisher, "Publisher")
        self.assertEqual(item.verification_status, "unverified")
        self.assertFalse(item.sales_verified)
        self.assertEqual(urlparse(seen["url"]).hostname, "news.google.com")

    def test_query_and_limit_validation(self):
        provider = GoogleNewsRSSProvider(fetcher=lambda *_: RSS)
        with self.assertRaises(ValueError):
            provider.search(" ")
        with self.assertRaises(ValueError):
            provider.search("query", limit=0)
        with self.assertRaises(ValueError):
            provider.search("x" * 301)

    def test_feed_size_is_bounded(self):
        provider = GoogleNewsRSSProvider(fetcher=lambda *_: b"x" * 1_000_001)
        with self.assertRaises(ValueError):
            provider.search("query")

    def test_network_fetch_rejects_wrong_hosts_and_schemes(self):
        provider = GoogleNewsRSSProvider()
        with self.assertRaises(ValueError):
            provider._fetcher("http://news.google.com/rss", 1)
        with self.assertRaises(ValueError):
            provider._fetcher("https://example.com/rss", 1)


if __name__ == "__main__":
    unittest.main()
