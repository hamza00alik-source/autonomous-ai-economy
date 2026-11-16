import base64
import tempfile
import unittest
from pathlib import Path

from economy.identity import ParticipantRegistry
from economy.work_records import WorkRecordStore


class WorkRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "participants.sqlite3"
        self.registry = ParticipantRegistry(self.path)
        self.provider = self._agent("provider", b"p" * 32)
        self.buyer = self._agent("buyer", b"b" * 32)
        self.adjudicator_key = base64.urlsafe_b64encode(b"j" * 32).decode().rstrip("=")
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

    def _submit(self, task="task-1"):
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

    def test_invalid_signature_and_duplicate_task_rejected(self):
        provider_id = self.provider["participant_id"]
        buyer_id = self.buyer["participant_id"]
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
