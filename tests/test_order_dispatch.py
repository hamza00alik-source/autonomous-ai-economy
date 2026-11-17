import json
import tempfile
import unittest
from pathlib import Path

from economy.order_dispatch import dispatch_accepted_orders
from economy.task_store import TaskStore


class AcceptedOrderDispatchTests(unittest.TestCase):
    def test_dispatch_is_idempotent_and_preserves_buyer_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TaskStore(Path(tmp) / "economy.sqlite3")
            class Agreements:
                def accepted_orders(self, *, limit):
                    self.limit = limit
                    return [{
                        "task_id": "order-1", "listing_id": "listing-1",
                        "buyer_id": "buyer-1", "provider_id": "agent-1",
                        "title": "Market research brief",
                        "scope": "Compare three public products",
                        "acceptance_criteria": "Include sources and comparison table",
                        "due_at": None, "price_minor": 1200,
                        "currency": "USD", "status": "accepted",
                    }][:limit]
            agreements = Agreements()
            first = dispatch_accepted_orders(agreements, store)
            second = dispatch_accepted_orders(agreements, store)
            self.assertEqual(first["discovered"], 1)
            self.assertEqual(second["discovered"], 1)
            tasks = store.list_tasks()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0]["assigned_agent"], "order-delivery-agent")
            objective = json.loads(tasks[0]["objective"])
            self.assertEqual(objective["task_id"], "order-1")
            self.assertEqual(objective["acceptance_criteria"],
                             "Include sources and comparison table")
            self.assertEqual(objective["price_minor"], 1200)
            self.assertIn("not delivery", first["notice"])


if __name__ == "__main__":
    unittest.main()
