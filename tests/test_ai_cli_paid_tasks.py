import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from economy.ai_cli import main
from economy.basedagents_marketplace import PaidTaskLead
from economy.basedagents_opportunities import PaidOpportunityStore


class PaidTaskCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_command_persists_opportunities_without_claiming(self):
        lead = PaidTaskLead(
            task_id="cli-task", title="Write a report", description="Research",
            category="research", bounty_usdc="3.00", network="eip155:8453",
            status="open", claimable=True,
        )

        class Provider:
            def search(self, *, limit):
                return [lead]

        with patch("economy.ai_cli.BasedAgentsPublicTasks", return_value=Provider()):
            with patch.object(sys, "argv", [
                "economy-ai", "--data-dir", str(self.data_dir),
                "scan-paid-tasks", "--limit", "5",
            ]):
                self.assertEqual(main(), 0)

        store = PaidOpportunityStore(self.data_dir / "paid-opportunities.sqlite3")
        self.assertEqual(len(store.list_review_required()), 1)

    def test_list_command_outputs_saved_review_queue(self):
        store = PaidOpportunityStore(self.data_dir / "paid-opportunities.sqlite3")
        store.save(PaidTaskLead(
            task_id="saved-task", title="Data task", description="Analyze",
            category="data", bounty_usdc="2.00", network="eip155:8453",
            status="open", claimable=True,
        ))
        with patch.object(sys, "argv", [
            "economy-ai", "--data-dir", str(self.data_dir), "list-paid-tasks",
        ]):
            self.assertEqual(main(), 0)


if __name__ == "__main__":
    unittest.main()
