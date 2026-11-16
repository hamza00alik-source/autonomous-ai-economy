import tempfile
import unittest
from pathlib import Path
from economy.agents import AgentRegistry, RuleBasedAgent
from economy.controller import EconomyController
from economy.ledger import AppendOnlyLedger
from economy.models import LedgerEntry, TaskStatus

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.registry = AgentRegistry()
        self.registry.register(RuleBasedAgent("research", "research"))
        self.controller = EconomyController(self.registry)

    def test_task_lifecycle(self):
        task = self.controller.submit("Scan", "Find a test opportunity", "research")
        result = self.controller.execute(task.task_id)
        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertIn("test opportunity", result.result)

    def test_unknown_agent_rejected(self):
        with self.assertRaises(KeyError):
            self.controller.submit("Scan", "Objective", "missing")

    def test_task_cannot_execute_twice(self):
        task = self.controller.submit("Scan", "Objective", "research")
        self.controller.execute(task.task_id)
        with self.assertRaises(ValueError):
            self.controller.execute(task.task_id)

    def test_ledger_is_simulated_and_balances(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = AppendOnlyLedger(Path(tmp) / "ledger.jsonl")
            ledger.append(LedgerEntry.create("income", 1250, "USD", "test income"))
            ledger.append(LedgerEntry.create("expense", 250, "USD", "test expense"))
            self.assertEqual(ledger.balance_minor(), 1000)
            self.assertTrue(all(row["simulated"] for row in ledger.entries()))

    def test_real_entries_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = AppendOnlyLedger(Path(tmp) / "ledger.jsonl")
            entry = LedgerEntry.create("income", 10, "USD", "test")
            from dataclasses import replace
            with self.assertRaises(ValueError):
                ledger.append(replace(entry, simulated=False))

if __name__ == "__main__":
    unittest.main()
