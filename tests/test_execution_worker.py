from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from economy.execution_worker import ApprovedExecutionWorker, ExecutionError
from economy.fulfillment import FulfillmentError, FulfillmentStore


FP = "c" * 64


def setup_job(root, *, state="in_progress", payload=None, agent="game-asset-builder"):
    approval = lambda token, job_id, action: token == f"owner:{job_id}:{action}"
    store = FulfillmentStore(
        root / "fulfillment.sqlite3",
        identity_verifier=lambda agent_id, fp: agent_id == agent and fp == FP,
        owner_approval_verifier=approval,
    )
    job = store.create_job(
        source="internal", external_id="product-pack-v1", agent_id=agent,
        agent_key_fingerprint=FP,
        payload=payload or {"execution_spec": {"kind": "moba_objective_props_v1"}},
        idempotency_key="internal-pack-v1",
    )
    store.transition(job.job_id, "owner_approved", actor="owner",
                     idempotency_key="approve-work",
                     owner_approval=f"owner:{job.job_id}:owner_approved")
    store.transition(job.job_id, "in_progress", actor="owner",
                     idempotency_key="start-work")
    return store, job


def make_worker(store, root, *, identity=True, execution=True):
    return ApprovedExecutionWorker(
        store, root / "artifacts",
        identity_verifier=(lambda *_: identity),
        execution_approval_verifier=(lambda token, job, action: execution and token == f"owner:{job}:{action}"),
    )


def test_executes_only_allowlisted_job_and_runs_structural_qa(tmp_path):
    store, job = setup_job(tmp_path)
    worker = make_worker(store, tmp_path)
    result = worker.execute(job.job_id, owner_execution_approval=f"owner:{job.job_id}:execute")
    assert result["state"] == "delivery_ready"
    assert result["qa"]["qa_passed"] is True
    assert result["qa"]["glb_models"] == 6
    assert result["published"] is False
    assert result["submitted"] is False
    assert store.get(job.job_id).state == "delivery_ready"
    assert Path(result["artifact_path"]).is_file()
    # Replaying the same request is idempotent and returns the same artifact.
    assert worker.execute(job.job_id, owner_execution_approval=f"owner:{job.job_id}:execute") == result


def test_execution_requires_fresh_owner_approval(tmp_path):
    store, job = setup_job(tmp_path)
    worker = make_worker(store, tmp_path, execution=False)
    with pytest.raises(ExecutionError, match="fresh owner approval"):
        worker.execute(job.job_id, owner_execution_approval="bad-token")


def test_execution_rejects_wrong_identity_and_unapproved_state(tmp_path):
    store, job = setup_job(tmp_path)
    worker = make_worker(store, tmp_path, identity=False)
    with pytest.raises(ExecutionError, match="identity"):
        worker.execute(job.job_id, owner_execution_approval=f"owner:{job.job_id}:execute")

    store2 = FulfillmentStore(
        tmp_path / "other.sqlite3", identity_verifier=lambda *_: True,
    )
    job2 = store2.create_job(source="internal", external_id="other",
        agent_id="game-asset-builder", agent_key_fingerprint=FP,
        payload={"execution_spec": {"kind": "moba_objective_props_v1"}},
        idempotency_key="other")
    worker2 = make_worker(store2, tmp_path / "other")
    with pytest.raises(ExecutionError, match="in_progress"):
        worker2.execute(job2.job_id, owner_execution_approval=f"owner:{job2.job_id}:execute")


def test_execution_rejects_unregistered_agent_and_arbitrary_task_text(tmp_path):
    store, job = setup_job(tmp_path, payload={"execution_spec": {"kind": "run_shell", "command": "rm -rf /"}})
    worker = make_worker(store, tmp_path)
    with pytest.raises(ExecutionError, match="allowlisted"):
        worker.execute(job.job_id, owner_execution_approval=f"owner:{job.job_id}:execute")

    store2, job2 = setup_job(tmp_path / "bad-agent", agent="unknown-agent")
    worker2 = make_worker(store2, tmp_path / "bad-agent")
    with pytest.raises(ExecutionError, match="no execution handler"):
        worker2.execute(job2.job_id, owner_execution_approval=f"owner:{job2.job_id}:execute")


def test_missing_execution_verifiers_are_rejected(tmp_path):
    store, _ = setup_job(tmp_path)
    with pytest.raises(ValueError, match="mandatory"):
        ApprovedExecutionWorker(store, tmp_path / "artifacts",
                                identity_verifier=None, execution_approval_verifier=lambda *_: True)

def test_external_marketplace_job_cannot_be_routed_to_internal_product_builder(tmp_path):
    approval = lambda token, job_id, action: token == f"owner:{job_id}:{action}"
    store = FulfillmentStore(
        tmp_path / "external.sqlite3",
        identity_verifier=lambda *_: True,
        owner_approval_verifier=approval,
    )
    job = store.create_job(
        source="taskmarket", external_id="external-task", agent_id="game-asset-builder",
        agent_key_fingerprint=FP,
        payload={"execution_spec": {"kind": "moba_objective_props_v1"}},
        idempotency_key="external-task",
    )
    store.transition(job.job_id, "owner_approved", actor="owner",
                     idempotency_key="approve-external",
                     owner_approval=f"owner:{job.job_id}:owner_approved")
    store.transition(job.job_id, "in_progress", actor="owner",
                     idempotency_key="start-external")
    worker = make_worker(store, tmp_path)
    with pytest.raises(ExecutionError, match="internal product jobs"):
        worker.execute(job.job_id, owner_execution_approval=f"owner:{job.job_id}:execute")
