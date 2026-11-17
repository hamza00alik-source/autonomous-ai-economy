import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from economy.identity import ParticipantRegistry
from economy.task_agreements import TaskAgreementStore
from economy.work_records import WorkRecordStore
from economy.local_delivery import accept_receipt_locally, submit_receipt_locally


class LocalDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "participants.sqlite3"
        self.registry = ParticipantRegistry(self.db_path)
        self.provider = self._agent("provider", b"p" * 32)
        self.buyer = self._agent("buyer", b"b" * 32)
        self.agreements = TaskAgreementStore(self.db_path, verifier=lambda *_: True)
        self.store = WorkRecordStore(self.db_path, verifier=lambda *_: True)
        self.artifact = self.root / "delivery.bin"
        self.artifact.write_bytes(b"buyer can verify these bytes")
        self.digest = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.task_id = "local-delivery-task"
        self._accepted_agreement()
        submitted = submit_receipt_locally(
            self.db_path, self.task_id, self.provider["participant_id"],
            self.buyer["participant_id"], "Deliverable attached by content digest",
            [self.artifact], signer=lambda payload: "valid", verifier=lambda *_: True,
        )
        self.receipt = submitted["receipt"]
        self.assertEqual(submitted["artifact_manifests"][0]["sha256"], self.digest)

    def tearDown(self):
        self.tmp.cleanup()

    def _agent(self, handle, raw_key):
        public_key = base64.urlsafe_b64encode(raw_key).decode().rstrip("=")
        challenge = self.registry.begin_agent_enrollment(handle, handle, public_key)
        return self.registry.complete_agent_enrollment(
            challenge["challenge_id"], "proof", verifier=lambda *_: True
        )

    def _accepted_agreement(self):
        buyer_id = self.buyer["participant_id"]
        provider_id = self.provider["participant_id"]
        payload = {"task_id": self.task_id, "buyer_id": buyer_id, "provider_id": provider_id}
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                """INSERT INTO task_agreements
                   (task_id,listing_id,buyer_id,provider_id,title,scope,
                    acceptance_criteria,offer_payload,buyer_signature,status,
                    created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,'accepted','now','now')""",
                (self.task_id, "listing", buyer_id, provider_id, "Test", "Scope",
                 "Exact bytes match", json.dumps(payload), "valid"),
            )

    def test_buyer_can_verify_and_accept_receipt_end_to_end(self):
        result = accept_receipt_locally(
            self.db_path, self.receipt["receipt_id"], self.buyer["participant_id"],
            [self.artifact], signer=lambda payload: "valid", verifier=lambda *_: True,
        )
        self.assertEqual(result["receipt"]["status"], "accepted")
        self.assertEqual(result["verified_artifacts"][0]["sha256"], self.digest)
        self.assertEqual(
            WorkRecordStore(self.db_path, verifier=lambda *_: True)
            .reputation(self.provider["participant_id"])["accepted"], 1,
        )

    def test_mismatched_file_does_not_accept_receipt(self):
        self.artifact.write_bytes(b"tampered but same task")
        with self.assertRaisesRegex(ValueError, "does not match"):
            accept_receipt_locally(
                self.db_path, self.receipt["receipt_id"], self.buyer["participant_id"],
                [self.artifact], signer=lambda payload: "valid", verifier=lambda *_: True,
            )
        self.assertEqual(self.store.get_receipt(self.receipt["receipt_id"])["status"], "submitted")

    def test_missing_artifact_does_not_accept_receipt(self):
        with self.assertRaisesRegex(ValueError, "missing locally verified"):
            accept_receipt_locally(
                self.db_path, self.receipt["receipt_id"], self.buyer["participant_id"],
                [], signer=lambda payload: "valid",
            )
        self.assertEqual(self.store.get_receipt(self.receipt["receipt_id"])["status"], "submitted")

    def test_wrong_buyer_cannot_accept_receipt(self):
        with self.assertRaisesRegex(ValueError, "not authorized"):
            accept_receipt_locally(
                self.db_path, self.receipt["receipt_id"], "not-the-buyer",
                [self.artifact], signer=lambda payload: "valid",
            )
        self.assertEqual(self.store.get_receipt(self.receipt["receipt_id"])["status"], "submitted")


if __name__ == "__main__":
    unittest.main()
