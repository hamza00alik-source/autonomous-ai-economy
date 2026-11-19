from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from economy.fulfillment import FulfillmentError, FulfillmentStore


FINGERPRINT = "a" * 64


def store_at(path):
    return FulfillmentStore(
        path,
        identity_verifier=lambda agent, fingerprint: agent == "builder-1" and fingerprint == FINGERPRINT,
        owner_approval_verifier=lambda token, job_id, action: token == f"approved:{job_id}:{action}",
        acceptance_verifier=lambda source, external_id, evidence: evidence.get("verified") is True,
        settlement_verifier=lambda source, external_id: {
            "verified": True, "net_amount": "1.80", "currency": "USDC",
            "settlement_reference": "0x" + "b" * 64,
        },
    )


def make_job(store):
    return store.create_job(
        source="taskmarket", external_id="task-001", agent_id="builder-1",
        agent_key_fingerprint=FINGERPRINT, payload={"title": "Build a small API"},
        idempotency_key="create-task-001",
    )


def test_full_lifecycle_requires_owner_gates_and_verified_settlement():
    with TemporaryDirectory() as directory:
        store = store_at(Path(directory) / "fulfillment.sqlite3")
        job = make_job(store)
        assert job.state == "discovered"
        with pytest.raises(FulfillmentError, match="owner approval"):
            store.transition(job.job_id, "owner_approved", actor="owner",
                             idempotency_key="approve-missing")
        store.transition(job.job_id, "owner_approved", actor="owner",
                         idempotency_key="approve-1",
                         owner_approval=f"approved:{job.job_id}:owner_approved")
        store.transition(job.job_id, "in_progress", actor="agent",
                         idempotency_key="start-1")
        store.transition(job.job_id, "qa", actor="agent", idempotency_key="qa-1")
        store.transition(job.job_id, "delivery_ready", actor="qa-agent",
                         idempotency_key="ready-1")
        with pytest.raises(FulfillmentError, match="owner approval"):
            store.transition(job.job_id, "submission_approved", actor="owner",
                             idempotency_key="submit-missing")
        store.transition(job.job_id, "submission_approved", actor="owner",
                         idempotency_key="submit-1",
                         owner_approval=f"approved:{job.job_id}:submission_approved")
        store.transition(job.job_id, "accepted", actor="platform",
                         idempotency_key="accepted-1", evidence={"verified": True, "acceptance_reference": "accepted-1"})
        store.transition(job.job_id, "payment_pending", actor="accounting",
                         idempotency_key="pending-1")
        settled = store.reconcile(job.job_id, idempotency_key="settled-1")
        assert settled.state == "reconciled"
        assert store.events(job.job_id)[-1]["evidence"]["net_amount"] == "1.80"


def test_rejects_unverified_or_unbound_agent_identity():
    with TemporaryDirectory() as directory:
        store = FulfillmentStore(Path(directory) / "fulfillment.sqlite3",
                                 identity_verifier=lambda *_: False)
        with pytest.raises(FulfillmentError, match="cryptographically verified"):
            make_job(store)


def test_rejects_illegal_state_skips_and_unverified_settlement():
    with TemporaryDirectory() as directory:
        store = FulfillmentStore(
            Path(directory) / "fulfillment.sqlite3",
            identity_verifier=lambda *_: True,
            acceptance_verifier=lambda *_: True,
            settlement_verifier=lambda *_: {"verified": False},
        )
        job = make_job(store)
        with pytest.raises(FulfillmentError, match="not allowed"):
            store.transition(job.job_id, "accepted", actor="agent",
                             idempotency_key="skip-to-accepted")
        store.transition(job.job_id, "owner_approved", actor="owner", idempotency_key="approve",
                         owner_approval=f"approved:{job.job_id}:owner_approved")
        store.transition(job.job_id, "in_progress", actor="agent", idempotency_key="start")
        store.transition(job.job_id, "qa", actor="agent", idempotency_key="qa")
        store.transition(job.job_id, "delivery_ready", actor="qa", idempotency_key="ready")
        store.transition(job.job_id, "submission_approved", actor="owner", idempotency_key="submit",
                         owner_approval=f"approved:{job.job_id}:submission_approved")
        store.transition(job.job_id, "accepted", actor="platform", idempotency_key="accept", evidence={"verified": True})
        store.transition(job.job_id, "payment_pending", actor="accounting", idempotency_key="pending")
        with pytest.raises(FulfillmentError, match="independently verified"):
            store.reconcile(job.job_id, idempotency_key="premature-settlement")


def test_idempotency_and_event_log_are_stable():
    with TemporaryDirectory() as directory:
        store = store_at(Path(directory) / "fulfillment.sqlite3")
        job = make_job(store)
        first = store.transition(job.job_id, "owner_approved", actor="owner",
                                 idempotency_key="same-key",
                                 owner_approval=f"approved:{job.job_id}:owner_approved")
        repeated = store.transition(job.job_id, "owner_approved", actor="owner",
                                    idempotency_key="same-key")
        assert repeated.state == first.state
        assert len(store.events(job.job_id)) == 2

def test_only_independently_verified_revenue_candidates_enter_fulfillment():
    with TemporaryDirectory() as directory:
        store = store_at(Path(directory) / "fulfillment.sqlite3")
        review_only = {
            "source": "jobbi", "external_id": "gig-1",
            "status": "needs_owner_review", "escrow_verified": False,
            "claim_allowed": False, "payment_verified": False,
        }
        with pytest.raises(FulfillmentError, match="not eligible"):
            store.create_from_candidate(review_only, agent_id="builder-1",
                                         agent_key_fingerprint=FINGERPRINT,
                                         idempotency_key="review-only")
        ready = {
            "source": "taskmarket", "external_id": "task-verified",
            "status": "ready_for_owner_review", "escrow_verified": True,
            "claim_allowed": False, "payment_verified": False,
            "title": "Verified task",
        }
        job = store.create_from_candidate(ready, agent_id="builder-1",
                                          agent_key_fingerprint=FINGERPRINT,
                                          idempotency_key="verified-task")
        assert job.state == "discovered"
        assert job.payload["title"] == "Verified task"
