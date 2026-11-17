import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from economy.cli import main
from economy.task_store import TaskStore


class AuditCliTests(unittest.TestCase):
    def test_verify_audit_command_reports_valid_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            store = TaskStore(data_dir / "economy.sqlite3")
            store.enqueue("Audit", "Verify command", "agent-a")
            output = io.StringIO()
            with patch.object(sys, "argv", ["economy", "verify-audit", "--data-dir", tmp]):
                with contextlib.redirect_stdout(output):
                    main()
            report = json.loads(output.getvalue())
            self.assertTrue(report["valid"])
            self.assertEqual(report["checked_events"], 1)

    def test_verify_audit_command_exits_nonzero_on_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            store = TaskStore(data_dir / "economy.sqlite3")
            task = store.enqueue("Audit", "Tamper test", "agent-a")
            with sqlite3.connect(store.path) as db:
                db.execute("UPDATE task_events SET details_json='{}' WHERE task_id=?",
                           (task["task_id"],))
            output = io.StringIO()
            with patch.object(sys, "argv", ["economy", "verify-audit", "--data-dir", tmp]):
                with contextlib.redirect_stdout(output):
                    with self.assertRaises(SystemExit) as raised:
                        main()
            self.assertEqual(raised.exception.code, 1)
            self.assertFalse(json.loads(output.getvalue())["valid"])


if __name__ == "__main__":
    unittest.main()
