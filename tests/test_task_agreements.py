import base64
import tempfile
import unittest
from pathlib import Path

from economy.identity import ParticipantRegistry
from economy.service_catalog import ServiceCatalog
from economy.task_agreements import TaskAgreementStore


class TaskAgreementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "participants.sqlite3"
        self.registry = ParticipantRegistry(self.path)
        self.provider = self._agent("provider", b"p" * 32)
        self.buyer = self._human("buyer", b"b" * 32)
        self.catalog = ServiceCatalog(self.path, verifier=lambda *_: True)
        payload = self.catalog.listing_payload(
            provider_id=self.provider["participant_id"], slug="design-work",
            title="Design service", description="Design deliverables",
            category="design", delivery_format="source files", terms="One delivery",
        )
        draft = self.catalog.create_draft(
            provider_id=self.provider["participant_id"], slug="design-work",
            title="Design service", description="Design deliverables",
            category="design", delivery_format="source files", terms="One delivery",
            signature="provider-signature",
        )
        self.listing = self.catalog.publish(
            draft["listing_id"], approval_ref="owner-approved",
            approval_verifier=lambda *_: True,
        )
        self.store = TaskAgreementStore(self.path, verifier=lambda *_: True)

    def tearDown(self):
        self.tmp.cleanup()

    def _agent(self, handle, key_bytes):
        key = base64.urlsafe_b64encode(key_bytes).decode().rstrip("=")
        challenge = self.registry.begin_agent_enrollment(handle, handle, key)
        return self.registry.complete_agent_enrollment(
            challenge["challenge_id"], "proof", verifier=lambda *_: True
        )

    def _human(self, handle, key_bytes):
        person = self.registry.create_human(handle, handle)
        key = base64.urlsafe_b64encode(key_bytes).decode().rstrip("=")
        challenge = self.registry.begin_key_binding(person["participant_id"], key)
        return self.registry.complete_key_binding(
            challenge["challenge_id"], "proof", verifier=lambda *_: True
        )

    def _offer(self, task_id="task-001"):
        fields = dict(
            task_id=task_id, listing_id=self.listing["listing_id"],
            buyer_id=self.buyer["participant_id"], provider_id=self.provider["participant_id"],
            title="Create a logo", scope="One original logo and source file",
            acceptance_criteria="SVG and PNG supplied; editable source included",
            price_minor=2500, currency="USD",
        )
        return self.store.create_offer(**fields, signature="buyer-signature")

    def test_buyer_offer_requires_provider_acceptance_before_work(self):
        offer = self._offer()
        self.assertEqual(offer["status"], "offered")
        response = self.store.response_signing_bytes(
            offer["task_id"], self.provider["participant_id"], "accept"
        )
        self.assertTrue(response)
        accepted = self.store.respond(
            offer["task_id"], provider_id=self.provider["participant_id"],
            decision="accept", signature="provider-acceptance",
        )
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(len(self.store.events(offer["task_id"])), 2)

    def test_provider_can_decline_and_buyer_can_withdraw_open_offer(self):
        declined = self._offer("task-decline")
        self.store.respond(
            declined["task_id"], provider_id=self.provider["participant_id"],
            decision="decline", signature="provider-decline",
        )
        self.assertEqual(self.store.get(declined["task_id"])["status"], "declined")
        withdrawn = self._offer("task-withdraw")
        self.store.withdraw(
            withdrawn["task_id"], buyer_id=self.buyer["participant_id"],
            signature="buyer-withdrawal",
        )
        self.assertEqual(self.store.get(withdrawn["task_id"])["status"], "withdrawn")

    def test_offer_must_reference_active_listing_owned_by_provider(self):
        with self.assertRaisesRegex(ValueError, "active listing owned by the provider"):
            self.store.create_offer(
                task_id="wrong-provider", listing_id=self.listing["listing_id"],
                buyer_id=self.buyer["participant_id"], provider_id=self.buyer["participant_id"],
                title="Work", scope="Scope", acceptance_criteria="Criteria",
                signature="buyer-signature",
            )

    def test_invalid_buyer_signature_and_duplicate_task_rejected(self):
        fields = dict(
            task_id="task-duplicate", listing_id=self.listing["listing_id"],
            buyer_id=self.buyer["participant_id"], provider_id=self.provider["participant_id"],
            title="Task", scope="Scope", acceptance_criteria="Criteria",
        )
        with self.assertRaisesRegex(ValueError, "buyer task-offer signature"):
            self.store.create_offer(**fields, signature="bad")
        self.store.create_offer(**fields, signature="buyer-signature")
        with self.assertRaises(Exception):
            self.store.create_offer(**fields, signature="buyer-signature")


if __name__ == "__main__":
    unittest.main()
