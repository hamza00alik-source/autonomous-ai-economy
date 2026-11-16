import tempfile
import unittest
from pathlib import Path

from economy.task_store import TaskStore
from economy.worker import run_once


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = TaskStore(Path(self.tmp.name) / "queue.sqlite3")

    def test_persists_across_instances_and_worker_completes(self):
        task = self.store.enqueue("Research", "Find evidence requirements", "opportunity-researcher")
        reopened = TaskStore(Path(self.tmp.name) / "queue.sqlite3")
        result = run_once(reopened)
        self.assertEqual(result["task_id"], task["task_id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(reopened.get(task["task_id"])["status"], "completed")
        self.assertEqual([e["event_type"] for e in reopened.events(task["task_id"])],
                         ["queued", "started", "completed"])

    def test_idempotency_key_returns_existing_task(self):
        first = self.store.enqueue("A", "B", "opportunity-researcher", "same-request")
        second = self.store.enqueue("A", "B", "opportunity-researcher", "same-request")
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(len(self.store.list_tasks()), 1)

    def test_claim_is_single_use_until_requeued(self):
        task = self.store.enqueue("A", "B", "opportunity-researcher")
        claimed = self.store.claim()
        self.assertEqual(claimed["task_id"], task["task_id"])
        self.assertIsNone(self.store.claim())

    def test_bounded_retry_then_terminal_failure(self):
        task = self.store.enqueue("A", "B", "missing-agent", max_attempts=2)
        first = self.store.claim()
        again = self.store.fail(first["task_id"], "missing agent")
        self.assertEqual(again["status"], "queued")
        second = self.store.claim()
        final = self.store.fail(second["task_id"], "missing agent")
        self.assertEqual(final["status"], "failed")
        self.assertEqual(final["attempts"], 2)

    def test_invalid_attempt_limit_rejected(self):
        with self.assertRaises(ValueError):
            self.store.enqueue("A", "B", "agent", max_attempts=99)


if __name__ == "__main__":
    unittest.main()
