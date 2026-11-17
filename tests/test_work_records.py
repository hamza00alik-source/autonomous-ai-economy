import base64
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from economy.identity import ParticipantRegistry
from economy.work_records import WorkRecordStore
from economy.task_agreements import TaskAgreementStore


class WorkRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "participants.sqlite3"
        self.registry = ParticipantRegistry(self.path)
        self.provider = self._agent("provider", b"p" * 32)
        self.buyer = self._agent("buyer", b"b" * 32)
        self.adjudicator_key = base64.urlsafe_b64encode(b"j" * 32).decode().rstrip("=")
        self.agreements = TaskAgreementStore(self.path)
        self.store = WorkRecordStore(
            self.path, adjudicators={"arbiter": self.adjudicator_key},
            verifier=lambda key, message, signature: signature == "valid",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _agent(self, handle, key_bytes):
        key = base64.urlsafe_b64encode(key_bytes).decode().rstrip("=")
        challenge = self.registry.begin_agent_enrollment(handle, handle, key)
        return self.registry.complete_agent_enrollment(
            challenge["challenge_id"], "proof", verifier=lambda *_: True
        )

    def _accepted_agreement(self, task_id):
        provider_id = self.provider["participant_id"]
        buyer_id = self.buyer["participant_id"]
        payload = {"task_id": task_id, "buyer_id": buyer_id, "provider_id": provider_id}
        with sqlite3.connect(self.path) as db:
            db.execute(
                """INSERT OR IGNORE INTO task_agreements
                   (task_id,listing_id,buyer_id,provider_id,title,scope,
                    acceptance_criteria,offer_payload,buyer_signature,status,
                    created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,'accepted','now','now')""",
                (task_id, "listing-test", buyer_id, provider_id, "Test work",
                 "Test scope", "Artifact delivered", json.dumps(payload), "valid"),
            )

    def _submit(self, task="task-1"):
        self._accepted_agreement(task)
        provider_id = self.provider["participant_id"]
        buyer_id = self.buyer["participant_id"]
        payload = self.store.submission_payload(
            task_id=task, provider_id=provider_id, buyer_id=buyer_id,
            summary="Completed test deliverable", evidence_refs=["artifact:sha256:abc"],
        )
        return self.store.submit(
            task_id=task, provider_id=provider_id, buyer_id=buyer_id,
            summary="Completed test deliverable", evidence_refs=["artifact:sha256:abc"],
            signature="valid",
        )

    def test_signed_submission_and_buyer_acceptance_drive_reputation(self):
        receipt = self._submit()
        self.assertEqual(receipt["status"], "submitted")
        self.assertEqual(self.store.reputation(self.provider["participant_id"])["pending"], 1)
        signature_payload = self.store.acceptance_payload(
            receipt["receipt_id"], self.buyer["participant_id"],
            self.provider["participant_id"],
        )
        self.assertTrue(signature_payload)
        accepted = self.store.accept(
            receipt["receipt_id"], buyer_id=self.buyer["participant_id"], signature="valid"
        )
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(self.store.reputation(self.provider["participant_id"])["accepted"], 1)

    def test_submission_fails_closed_without_task_agreement_schema(self):
        isolated_path = Path(self.tmp.name) / "isolated.sqlite3"
        isolated_registry = ParticipantRegistry(isolated_path)
        provider = self._agent("isolated-provider", b"i" * 32)
        buyer = self._agent("isolated-buyer", b"c" * 32)
        isolated_store = WorkRecordStore(
            isolated_path, verifier=lambda *_: True,
        )
        with self.assertRaisesRegex(ValueError, "agreement store is unavailable"):
            isolated_store.submit(
                task_id="unlinked", provider_id=provider["participant_id"],
                buyer_id=buyer["participant_id"], summary="Unlinked work",
                evidence_refs=["artifact:unlinked"], signature="valid",
            )

    def test_invalid_signature_and_duplicate_task_rejected(self):
        provider_id = self.provider["participant_id"]
        buyer_id = self.buyer["participant_id"]
        self._accepted_agreement("invalid")
        with self.assertRaisesRegex(ValueError, "signature"):
            self.store.submit(
                task_id="invalid", provider_id=provider_id, buyer_id=buyer_id,
                summary="Work", evidence_refs=["artifact:x"], signature="bad",
            )
        self._submit()
        with self.assertRaises(Exception):
            self._submit()

    def test_dispute_freezes_acceptance_reputation_until_resolution(self):
        receipt = self._submit()
        dispute_id = "dispute"
        payload = self.store.dispute_payload(
            receipt["receipt_id"], dispute_id, self.buyer["participant_id"],
            "Deliverable incomplete", ["artifact:review"],
        )
        self.assertTrue(payload)
        dispute = self.store.open_dispute(
            receipt["receipt_id"], actor_id=self.buyer["participant_id"],
            reason="Deliverable incomplete", evidence_refs=["artifact:review"],
            signature="valid",
        )
        self.assertEqual(dispute["status"], "open")
        with self.assertRaisesRegex(ValueError, "already has an open dispute"):
            self.store.open_dispute(
                receipt["receipt_id"], actor_id=self.provider["participant_id"],
                reason="Duplicate dispute", evidence_refs=["artifact:other"], signature="valid",
            )
        self.assertEqual(self.store.reputation(self.provider["participant_id"])["disputed"], 1)
        self.store.resolve_dispute(
            dispute["dispute_id"], resolver_id="arbiter", outcome="provider_favor",
            note="Evidence supports completion", signature="valid",
        )
        reputation = self.store.reputation(self.provider["participant_id"])
        self.assertEqual(reputation["resolved_provider_favor"], 1)
        self.assertEqual(reputation["accepted"], 0)

    def test_only_trusted_adjudicator_can_resolve(self):
        receipt = self._submit()
        dispute = self.store.open_dispute(
            receipt["receipt_id"], actor_id=self.buyer["participant_id"],
            reason="Need review", evidence_refs=["artifact:review"], signature="valid",
        )
        with self.assertRaisesRegex(ValueError, "trusted adjudicator"):
            self.store.resolve_dispute(
                dispute["dispute_id"], resolver_id="unknown", outcome="buyer_favor",
                note="review", signature="valid",
            )


if __name__ == "__main__":
    unittest.main()
