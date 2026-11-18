import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from economy.financial_console import main


class FinancialConsoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "data"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        output = io.StringIO()
        with patch.object(sys, "argv", ["economy-finance", "--data-dir", str(self.data), *args]):
            with contextlib.redirect_stdout(output):
                code = main()
        self.assertEqual(code, 0)
        return output.getvalue()

    def test_empty_policy_and_schedule_inventory_is_readable(self):
        self.assertEqual(json.loads(self.run_cli("policies")), [])
        self.assertEqual(json.loads(self.run_cli("schedules")), [])

    def test_emergency_pause_all_is_idempotent_and_local(self):
        first = json.loads(self.run_cli("pause-all"))
        second = json.loads(self.run_cli("pause-all"))
        self.assertEqual(first["paused_schedules"], 0)
        self.assertEqual(second["paused_schedules"], 0)
        self.assertIn("paused", second["message"])

    def test_policy_template_writes_normalized_unsigned_terms_without_overwrite(self):
        output = self.data / "policy-template.json"
        self.run_cli(
            "policy-template", "--policy-id", "ops", "--version", "1",
            "--owner-id", "owner", "--agent-id", "agent", "--currency", "USD",
            "--per-transaction-limit-minor", "250",
            "--daily-spend-limit-minor", "500",
            "--destination", "service:compute", "--output", str(output),
        )
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["allowed_destinations"], ["service:compute"])
        self.assertEqual(payload["per_transaction_limit_minor"], 250)
        with self.assertRaises(SystemExit):
            self.run_cli(
                "policy-template", "--policy-id", "ops", "--version", "1",
                "--owner-id", "owner", "--agent-id", "agent", "--currency", "USD",
                "--per-transaction-limit-minor", "250",
                "--daily-spend-limit-minor", "500",
                "--destination", "service:compute", "--output", str(output),
            )


if __name__ == "__main__":
    unittest.main()
