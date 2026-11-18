import json
import unittest
from urllib.parse import urlparse

from economy.basedagents_marketplace import BasedAgentsPublicTasks


class BasedAgentsMarketplaceTests(unittest.TestCase):
    def test_reads_current_schema_and_fails_closed_on_missing_claimable(self):
        seen = {}
        payload = {"tasks": [
            {"task_id": "task_1", "title": "Write a report", "description": "Research",
             "category": "research", "status": "open", "claimable": True,
             "bounty": {"amount_atomic": "2500000", "network": "eip155:8453"},
             "payment_status": "pending", "payment_verified": 0, "escrow": None},
            {"task_id": "task_2", "title": "Missing claimable", "status": "open",
             "bounty_amount": "100000", "bounty_network": "eip155:8453"},
            {"task_id": "task_3", "title": "Closed", "status": "verified"},
            {"title": "Malformed", "status": "open"},
        ]}
        def fetch(url, timeout):
            seen["url"] = url
            return json.dumps(payload).encode()

        leads = BasedAgentsPublicTasks(fetcher=fetch).search(limit=10)
        self.assertEqual(len(leads), 2)
        self.assertEqual(leads[0].bounty_usdc, "2.5")
        self.assertEqual(leads[0].network, "eip155:8453")
        self.assertFalse(leads[0].payment_verified)
        self.assertEqual(leads[0].payment_status, "pending")
        self.assertFalse(leads[1].claimable)
        self.assertEqual(leads[1].bounty_usdc, "0.1")
        self.assertEqual(urlparse(seen["url"]).hostname, "api.basedagents.ai")

    def test_reads_payment_endpoint_separately(self):
        calls = []
        def fetch(url, timeout):
            calls.append(url)
            return json.dumps({"payment": {
                "task_id": "task_1", "status": "pending",
                "verified": False, "settled": False, "tx_hash": None,
                "escrow": None,
            }}).encode()
        payment = BasedAgentsPublicTasks(fetcher=fetch).get_task_payment("task_1")
        self.assertEqual(payment["status"], "pending")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].endswith("/v1/tasks/task_1/payment"))

    def test_detail_preserves_top_level_payment_summary(self):
        provider = BasedAgentsPublicTasks(fetcher=lambda *_: json.dumps({
            "task": {"task_id": "task_1", "status": "open"},
            "payment": {"status": "pending", "verified": False},
        }).encode())
        task = provider.get_task("task_1")
        self.assertEqual(task["payment"]["status"], "pending")

    def test_rejects_invalid_pagination_and_task_ids(self):
        provider = BasedAgentsPublicTasks(fetcher=lambda *_: b'{"tasks":[]}')
        with self.assertRaises(ValueError):
            provider.search(limit=0)
        with self.assertRaises(ValueError):
            provider.search(offset=-1)
        with self.assertRaises(ValueError):
            provider.get_task("../agents")
        with self.assertRaises(ValueError):
            provider.get_task_payment("x/y")

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
