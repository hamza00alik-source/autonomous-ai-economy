import json
from pathlib import Path

import pytest

from economy.artifact_export import export_completed_order_artifact
from economy.task_store import TaskStore


def _completed_order(store, *, agent="order-delivery-agent", task_id="order-1"):
    order = {
        "schema": "aae.accepted-order/v1", "task_id": task_id,
        "title": "Competitor comparison", "scope": "Compare three products",
        "acceptance_criteria": "Include source links",
        "due_at": None, "price_minor": 1200, "currency": "USD",
        "buyer_id": "buyer-1", "provider_id": "agent-1",
    }
    queued = store.enqueue(
        "Customer order: Competitor comparison",
        json.dumps(order, sort_keys=True, separators=(",", ":")),
        agent, idempotency_key="test:" + task_id,
    )
    claimed = store.claim(allowed_agent_ids=[agent])
    assert claimed["task_id"] == queued["task_id"]
    result = (
        "# Customer order execution draft\n\n"
        "**Status:** DRAFT — not delivered or buyer-approved\n\n"
        "**Order:** Competitor comparison\n"
        f"**Task ID:** {task_id}\n\n"
        "## Payment status\nNot verified. No payment was collected or recorded.\n"
    )
    store.finish(claimed["task_id"], result, claimed["lease_token"])
    return queued["task_id"]


def test_exports_completed_order_as_private_content_addressed_artifact(tmp_path):
    store = TaskStore(tmp_path / "economy.sqlite3")
    task_id = _completed_order(store)
    output = tmp_path / "deliverables"
    first = export_completed_order_artifact(store, task_id, output)
    second = export_completed_order_artifact(store, task_id, output)
    artifact = Path(first["path"])
    assert artifact.is_file()
    assert artifact.read_text().startswith("# Customer order execution draft")
    assert first["manifest"]["sha256"] == second["manifest"]["sha256"]
    assert first["status"] == "draft_artifact_exported"
    assert "not completed domain work" in first["notice"]
    assert artifact.stat().st_mode & 0o777 == 0o600


def test_export_refuses_overwrite_if_artifact_bytes_changed(tmp_path):
    store = TaskStore(tmp_path / "economy.sqlite3")
    task_id = _completed_order(store)
    output = tmp_path / "deliverables"
    first = export_completed_order_artifact(store, task_id, output)
    Path(first["path"]).write_text("tampered")
    with pytest.raises(ValueError, match="different or unsafe content"):
        export_completed_order_artifact(store, task_id, output)


def test_export_refuses_non_order_agent_and_unfinished_tasks(tmp_path):
    store = TaskStore(tmp_path / "economy.sqlite3")
    task_id = _completed_order(store, agent="verification-auditor")
    with pytest.raises(ValueError, match="only completed order-delivery-agent"):
        export_completed_order_artifact(store, task_id, tmp_path / "deliverables")
