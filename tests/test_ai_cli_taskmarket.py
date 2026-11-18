import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from economy.ai_cli import main
from economy.taskmarket_marketplace import TaskmarketOpportunityStore


TASK_ID = "0x" + "a" * 64


class TaskmarketCliTests(unittest.TestCase):
    def test_scan_cli_persists_only_local_review_data(self):
        lead = {
            "task_id": TASK_ID, "reference_code": "TSK-TEST1234",
            "title": "Research report",
            "description": "Produce a technical report. Deliver a Markdown report and submit it for review. Acceptance requires five sources and accurate calculations.",
            "chain_id": 8453, "mode": "bounty", "status": "open", "phase": "active",
            "reward_base_units": "5000000", "reward_usdc": "5.000000",
            "net_reward_usdc": "5.000000", "escrow_tx_hash": "0x" + "b" * 64,
            "escrow_tracked": True, "escrow_booked_base_units": "5000000",
            "submission_count": 0, "award_count": 0,
            "expiry_time": "2030-01-01T00:00:00Z", "submission_window_open": True,
            "stake_required": False, "stake_bps": 0, "platform_fee_bps": 0,
            "tags": ["research"], "requester_actor_type": "agent",
        }
        class Provider:
            def search(self, *, limit):
                return [type("Lead", (), {"to_dict": lambda self: lead, **lead})()]
        with tempfile.TemporaryDirectory() as tmp:
            with patch("economy.ai_cli.TaskmarketPublicTasks", return_value=Provider()):
                with patch.object(sys, "argv", [
                    "economy-ai", "--data-dir", tmp, "scan-taskmarket-tasks",
                ]):
                    self.assertEqual(main(), 0)
            store = TaskmarketOpportunityStore(Path(tmp) / "taskmarket-opportunities.sqlite3")
            rows = store.list_opportunities()
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]["evaluation"]["claim_allowed"])

    def test_list_cli_can_show_only_qualified(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sys, "argv", [
                "economy-ai", "--data-dir", tmp, "list-taskmarket-tasks", "--qualified-only",
            ]):
                self.assertEqual(main(), 0)


if __name__ == "__main__":
    unittest.main()
