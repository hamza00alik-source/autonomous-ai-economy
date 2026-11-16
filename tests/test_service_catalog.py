import base64
import tempfile
import unittest
from pathlib import Path

from economy.identity import ParticipantRegistry
from economy.service_catalog import CatalogApprovalStore, ServiceCatalog


class ServiceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "participants.sqlite3"
        self.registry = ParticipantRegistry(self.path)
        key = base64.urlsafe_b64encode(b"s" * 32).decode().rstrip("=")
        challenge = self.registry.begin_agent_enrollment("seller", "Seller Agent", key)
        self.provider = self.registry.complete_agent_enrollment(
            challenge["challenge_id"], "proof", verifier=lambda *_: True
        )
        self.store = ServiceCatalog(self.path, verifier=lambda key, payload, sig: sig == "valid")

    def tearDown(self):
        self.tmp.cleanup()

    def _draft(self):
        fields = dict(
            provider_id=self.provider["participant_id"], slug="research-report",
            title="Market research report", description="Evidence-led market research",
            category="research", delivery_format="PDF report",
            terms="One delivery; revisions by agreement",
        )
        signature = "valid"
        return self.store.create_draft(**fields, signature=signature)

    def test_draft_is_not_discoverable_until_approval(self):
        listing = self._draft()
        self.assertEqual(listing["status"], "draft")
        self.assertEqual(self.store.discover(), [])
        with self.assertRaisesRegex(ValueError, "approval verifier"):
            self.store.publish(listing["listing_id"], approval_ref="token")
        with self.assertRaisesRegex(ValueError, "approval is invalid"):
            self.store.publish(listing["listing_id"], approval_ref="bad",
                               approval_verifier=lambda *_: False)
        active = self.store.publish(listing["listing_id"], approval_ref="approved",
                                    approval_verifier=lambda ref, payload: ref == "approved" and bool(payload))
        self.assertEqual(active["status"], "active")
        self.assertEqual(len(self.store.discover(query="research")), 1)

    def test_hmac_approval_token_is_exact_listing_bound_and_single_use(self):
        listing = self._draft()
        payload = self.store.publication_payload(listing["listing_id"], listing["payload"])
        secret = "x" * 48
        token = CatalogApprovalStore.create_token(listing["listing_id"], payload, secret)
        active = self.store.publish_with_token(
            listing["listing_id"], approval_token=token, approval_secret=secret
        )
        self.assertEqual(active["status"], "active")
        approvals = CatalogApprovalStore(self.path)
        valid, reason = approvals.consume(token, listing["listing_id"], payload, secret)
        self.assertFalse(valid)
        self.assertIn("already been used", reason)

    def test_catalog_approval_rejects_wrong_secret_and_listing_fingerprint(self):
        listing = self._draft()
        payload = self.store.publication_payload(listing["listing_id"], listing["payload"])
        token = CatalogApprovalStore.create_token(listing["listing_id"], payload, "y" * 48)
        approvals = CatalogApprovalStore(self.path)
        valid, _ = approvals.consume(token, listing["listing_id"], payload, "z" * 48)
        self.assertFalse(valid)
        valid, reason = approvals.consume(token, listing["listing_id"], b"changed", "y" * 48)
        self.assertFalse(valid)
        self.assertIn("exact listing", reason)

    def test_provider_can_withdraw_signed_listing(self):
        listing = self._draft()
        self.store.publish(listing["listing_id"], approval_ref="approved",
                           approval_verifier=lambda *_: True)
        self.store.withdraw(
            listing["listing_id"], provider_id=self.provider["participant_id"],
            signature="valid",
        )
        self.assertEqual(self.store.discover(), [])
        self.assertEqual(self.store.get(listing["listing_id"])["status"], "withdrawn")

    def test_human_participant_can_create_signed_service_draft(self):
        person = self.registry.create_human("human-seller", "Human Seller")
        key = base64.urlsafe_b64encode(b"h" * 32).decode().rstrip("=")
        challenge = self.registry.begin_key_binding(person["participant_id"], key)
        self.registry.complete_key_binding(
            challenge["challenge_id"], "proof", verifier=lambda *_: True
        )
        listing = self.store.create_draft(
            provider_id=person["participant_id"], slug="human-service",
            title="Human service", description="A human-delivered service",
            category="design", delivery_format="source files", terms="One delivery",
            signature="valid",
        )
        self.assertEqual(listing["provider_id"], person["participant_id"])
        self.assertEqual(listing["status"], "draft")

    def test_listing_requires_provider_signature_and_valid_slug(self):
        with self.assertRaisesRegex(ValueError, "slug"):
            self.store.create_draft(
                provider_id=self.provider["participant_id"], slug="Bad Slug",
                title="Title", description="Description", category="research",
                delivery_format="PDF", terms="Terms", signature="valid",
            )
        fields = dict(
            provider_id=self.provider["participant_id"], slug="valid-slug",
            title="Title", description="Description", category="research",
            delivery_format="PDF", terms="Terms",
        )
        with self.assertRaisesRegex(ValueError, "signature"):
            self.store.create_draft(**fields, signature="bad")


if __name__ == "__main__":
    unittest.main()
