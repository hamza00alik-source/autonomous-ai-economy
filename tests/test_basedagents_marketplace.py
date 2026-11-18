import json
import unittest
from urllib.parse import urlparse

from economy.basedagents_marketplace import BasedAgentsPublicTasks


class BasedAgentsMarketplaceTests(unittest.TestCase):
    def test_reads_only_open_tasks_and_marks_payment_unverified(self):
        seen = {}
        payload = {"tasks": [
            {"task_id": "task_1", "title": "Write a report", "description": "Research",
             "category": "research", "status": "open", "claimable": True,
             "bounty": {"amount_atomic": "2500000", "network": "eip155:8453"}},
            {"task_id": "task_2", "title": "Closed", "status": "verified"},
            {"title": "Malformed", "status": "open"},
        ]}
        def fetch(url, timeout):
            seen["url"] = url
            return json.dumps(payload).encode()

        leads = BasedAgentsPublicTasks(fetcher=fetch).search(limit=10)
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0].bounty_usdc, "2.50")
        self.assertEqual(leads[0].network, "eip155:8453")
        self.assertEqual(leads[0].verification_status, "unverified")
        self.assertFalse(leads[0].payment_verified)
        self.assertEqual(urlparse(seen["url"]).hostname, "api.basedagents.ai")

    def test_rejects_invalid_pagination(self):
        provider = BasedAgentsPublicTasks(fetcher=lambda *_: b'{"tasks":[]}')
        with self.assertRaises(ValueError):
            provider.search(limit=0)
        with self.assertRaises(ValueError):
            provider.search(offset=-1)

    def test_rejects_oversized_response(self):
        provider = BasedAgentsPublicTasks(fetcher=lambda *_: b"x" * 1_000_001)
        with self.assertRaises(ValueError):
            provider.search()

    def test_rejects_untrusted_host(self):
        provider = BasedAgentsPublicTasks()
        with self.assertRaises(ValueError):
            provider._fetcher("https://example.com/tasks", 1)


if __name__ == "__main__":
    unittest.main()
