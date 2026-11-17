import base64
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from economy.identity import ParticipantRegistry
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
        with patch("economy.worker.ensure_sandbox_available"), patch(
            "economy.worker.execute_builtin", return_value="sandboxed deterministic result"
        ):
            result = run_once(reopened)
        self.assertEqual(result["task_id"], task["task_id"])
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(result["lease_token"])
        self.assertEqual(reopened.get(task["task_id"])["status"], "completed")
        with self.assertRaisesRegex(ValueError, "lease"):
            reopened.finish(task["task_id"], "attempted replay", "replayed-token")
        self.assertEqual([e["event_type"] for e in reopened.events(task["task_id"])],
                         ["queued", "started", "completed"])

    def test_event_hash_chain_verifies_and_detects_event_tampering(self):
        task = self.store.enqueue("Audit", "Verify event integrity", "opportunity-researcher")
        claim = self.store.claim()
        self.store.finish(task["task_id"], "done", claim["lease_token"])
        verified = self.store.verify_event_chain()
        self.assertTrue(verified["valid"])
        self.assertEqual(verified["checked_events"], 3)
        with sqlite3.connect(self.store.path) as db:
            db.execute(
                "UPDATE task_events SET details_json='{}' WHERE event_id=1"
            )
        corrupted = self.store.verify_event_chain()
        self.assertFalse(corrupted["valid"])
        self.assertEqual(corrupted["failed_event_id"], 1)
        self.assertEqual(corrupted["reason"], "event_hash_mismatch")

    def test_event_hash_chain_detects_deleted_or_reordered_history(self):
        first = self.store.enqueue("First", "First event", "agent-a")
        self.store.enqueue("Second", "Second event", "agent-b")
        with sqlite3.connect(self.store.path) as db:
            db.execute("DELETE FROM task_events WHERE task_id=?", (first["task_id"],))
        result = self.store.verify_event_chain()
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "previous_hash_mismatch")

    def test_legacy_event_history_is_backfilled_once(self):
        legacy_path = Path(self.tmp.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy_path) as db:
            db.executescript("""
                CREATE TABLE tasks (
                    task_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE,
                    title TEXT NOT NULL, objective TEXT NOT NULL,
                    assigned_agent TEXT NOT NULL, status TEXT NOT NULL,
                    result TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, lease_until TEXT, lease_token TEXT
                );
                CREATE TABLE task_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL, details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT INTO tasks VALUES('legacy-task',NULL,'Legacy','Migrate','agent',
                    'queued',NULL,0,3,'2026-01-01T00:00:00+00:00',
                    '2026-01-01T00:00:00+00:00',NULL,NULL);
                INSERT INTO task_events(task_id,event_type,details_json,created_at)
                    VALUES('legacy-task','queued','{}','2026-01-01T00:00:00+00:00');
            """)
        migrated = TaskStore(legacy_path)
        self.assertTrue(migrated.verify_event_chain()["valid"])
        self.assertEqual(migrated.verify_event_chain()["checked_events"], 1)

    def test_idempotency_key_returns_existing_task(self):
        first = self.store.enqueue("A", "B", "opportunity-researcher", "same-request")
        second = self.store.enqueue("A", "B", "opportunity-researcher", "same-request")
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(len(self.store.list_tasks()), 1)

    def test_claim_is_single_use_until_requeued(self):
        task = self.store.enqueue("A", "B", "opportunity-researcher")
        claimed = self.store.claim()
        self.assertEqual(claimed["task_id"], task["task_id"])
        self.assertTrue(claimed["lease_token"])
        self.assertIsNone(self.store.claim())

    def test_missing_sandbox_does_not_claim_or_consume_tasks(self):
        from economy.builtin_process import SandboxUnavailable
        task = self.store.enqueue("Sandbox required", "Keep queued", "opportunity-researcher")
        with patch("economy.worker.ensure_sandbox_available",
                   side_effect=SandboxUnavailable("bubblewrap unavailable")):
            with self.assertRaises(SandboxUnavailable):
                run_once(self.store)
        current = self.store.get(task["task_id"])
        self.assertEqual(current["status"], "queued")
        self.assertEqual(current["attempts"], 0)

    def test_worker_leaves_tasks_for_unregistered_agents_queued(self):
        from economy.agents import AgentRegistry, RuleBasedAgent
        self.store.enqueue("Unknown", "Do not consume", "not-registered")
        registry = AgentRegistry()
        registry.register(RuleBasedAgent("known-agent", "safe test"))
        self.assertIsNone(run_once(self.store, registry))
        task = self.store.list_tasks()[0]
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["attempts"], 0)

    def test_worker_claims_only_matching_registered_agent(self):
        from economy.agents import AgentRegistry, RuleBasedAgent
        unknown = self.store.enqueue("Unknown", "Leave queued", "not-registered")
        known = self.store.enqueue("Known", "Execute safely", "known-agent")
        registry = AgentRegistry()
        registry.register(RuleBasedAgent("known-agent", "safe test"))
        result = run_once(self.store, registry)
        self.assertEqual(result["task_id"], known["task_id"])
        self.assertEqual(self.store.get(unknown["task_id"])["status"], "queued")

    def test_bounded_retry_then_terminal_failure(self):
        task = self.store.enqueue("A", "B", "missing-agent", max_attempts=2)
        first = self.store.claim()
        again = self.store.fail(first["task_id"], "missing agent", first["lease_token"])
        self.assertEqual(again["status"], "queued")
        second = self.store.claim()
        final = self.store.fail(second["task_id"], "missing agent", second["lease_token"])
        self.assertEqual(final["status"], "failed")
        self.assertEqual(final["attempts"], 2)

 
    def test_expired_lease_cannot_finish_before_recovery(self):
        task = self.store.enqueue("Expired lease", "Reject late completion", "opportunity-researcher")
        claim = self.store.claim()
        with sqlite3.connect(self.store.path) as db:
            db.execute("UPDATE tasks SET lease_until='2000-01-01T00:00:00+00:00' WHERE task_id=?",
                       (task["task_id"],))
        with self.assertRaisesRegex(ValueError, "expired"):
            self.store.finish(task["task_id"], "late result", claim["lease_token"])

    def test_stale_worker_cannot_finish_or_fail_after_lease_recovery(self):
        task = self.store.enqueue("Lease race", "Reject stale worker", "opportunity-researcher")
        old = self.store.claim()
        with sqlite3.connect(self.store.path) as db:
            db.execute("UPDATE tasks SET lease_until='2000-01-01T00:00:00+00:00' WHERE task_id=?",
                       (task["task_id"],))
        current = self.store.claim()
        with self.assertRaisesRegex(ValueError, "lease"):
            self.store.finish(task["task_id"], "stale result", old["lease_token"])
        with self.assertRaisesRegex(ValueError, "lease"):
            self.store.fail(task["task_id"], "stale error", old["lease_token"])
        completed = self.store.finish(task["task_id"], "current result", current["lease_token"])
        self.assertEqual(completed["status"], "completed")

    def test_expired_worker_lease_is_recovered(self):
        task = self.store.enqueue("Crash test", "Recover an interrupted task", "opportunity-researcher")
        claimed = self.store.claim()
        with sqlite3.connect(self.store.path) as db:
            db.execute("UPDATE tasks SET lease_until='2000-01-01T00:00:00+00:00' WHERE task_id=?",
                       (task["task_id"],))
        recovered = self.store.claim()
        self.assertEqual(recovered["task_id"], task["task_id"])
        self.assertNotEqual(recovered["lease_token"], claimed["lease_token"])
        self.assertEqual(recovered["status"], "running")
        self.assertEqual(recovered["attempts"], 2)
        kinds = [e["event_type"] for e in self.store.events(task["task_id"])]
        self.assertIn("lease_expired_retry", kinds)

    def test_verified_agent_participant_receives_scoped_task(self):
        registry = ParticipantRegistry(Path(self.tmp.name) / "participants.sqlite3")
        public_key = base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("=")
        challenge = registry.begin_agent_enrollment("worker-a", "Worker A", public_key)
        agent = registry.complete_agent_enrollment(
            challenge["challenge_id"], "valid", verifier=lambda *_: True
        )
        task = self.store.enqueue_for_participant(
            "Analyze opportunity", "Collect independent evidence",
            agent["participant_id"], registry, idempotency_key="agent-task-1",
        )
        self.assertEqual(task["assigned_agent"], agent["participant_id"])
        self.assertEqual(
            [item["task_id"] for item in self.store.list_for_agent(agent["participant_id"])],
            [task["task_id"]],
        )
        self.assertEqual(self.store.list_for_agent("worker-a"), [])

    def test_participant_assignment_rejects_humans_and_unknown_ids(self):
        registry = ParticipantRegistry(Path(self.tmp.name) / "participants.sqlite3")
        human = registry.create_human("human-a", "Human A")
        with self.assertRaisesRegex(ValueError, "only be assigned to agent"):
            self.store.enqueue_for_participant(
                "Task", "Objective", human["participant_id"], registry
            )
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.store.enqueue_for_participant(
                "Task", "Objective", "agent_unknown", registry
            )

    def test_invalid_attempt_limit_rejected(self):
        with self.assertRaises(ValueError):
            self.store.enqueue("A", "B", "agent", max_attempts=99)


    def test_list_for_agent_is_scoped_and_limited(self):
        self.store.enqueue("A", "objective A", "agent-a")
        self.store.enqueue("B", "objective B", "agent-b")
        self.store.enqueue("C", "objective C", "agent-a")
        rows = self.store.list_for_agent("agent-a", status="queued", limit=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["assigned_agent"], "agent-a")
        self.assertEqual(self.store.list_for_agent("agent-missing"), [])
if __name__ == "__main__":
    unittest.main()
