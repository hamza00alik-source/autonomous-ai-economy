import json
import threading
from pathlib import Path

import pytest

from economy.supervisor import supervise
from economy.task_store import TaskStore


class Store:
    pass


def test_supervisor_counts_completed_and_idle_cycles():
    results = iter([{"status": "completed"}, None, {"status": "completed"}])
    stats = supervise(Store(), poll_seconds=0.1, max_cycles=3,
                      worker=lambda _store: next(results))
    assert stats == {"cycles": 3, "completed": 2, "idle": 1, "errors": 0}


def test_supervisor_counts_worker_exceptions_and_continues():
    calls = 0

    def worker(_store):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary failure")
        return {"status": "completed"}

    stats = supervise(Store(), poll_seconds=0.1, max_cycles=2, worker=worker)
    assert stats == {"cycles": 2, "completed": 1, "idle": 0, "errors": 1}


def test_supervisor_stops_before_first_cycle_when_requested():
    stop = threading.Event()
    stop.set()
    stats = supervise(Store(), poll_seconds=0.1, stop_event=stop,
                      worker=lambda _store: pytest.fail("must not run"))
    assert stats == {"cycles": 0, "completed": 0, "idle": 0, "errors": 0}


def test_supervisor_rejects_unbounded_poll_values():
    with pytest.raises(ValueError):
        supervise(Store(), poll_seconds=0.01, max_cycles=0)
    with pytest.raises(ValueError):
        supervise(Store(), poll_seconds=301, max_cycles=0)


def test_supervisor_can_be_stopped_by_worker_callback():
    stop = threading.Event()

    def worker(_store):
        stop.set()
        return {"status": "completed"}

    stats = supervise(Store(), poll_seconds=0.1, stop_event=stop, worker=worker)
    assert stats == {"cycles": 1, "completed": 1, "idle": 0, "errors": 0}


def test_supervisor_rejects_negative_cycle_limit():
    with pytest.raises(ValueError):
        supervise(Store(), poll_seconds=0.1, max_cycles=-1)

def test_supervisor_dispatches_accepted_orders_before_worker_cycle():
    class Queue:
        def __init__(self):
            self.items = {}
        def enqueue(self, title, objective, assigned_agent, idempotency_key, max_attempts):
            item = self.items.setdefault(idempotency_key, {
                "task_id": "queue-1", "status": "queued",
                "title": title, "objective": objective,
                "assigned_agent": assigned_agent,
            })
            return item

    class Agreements:
        def accepted_orders(self, *, limit):
            return [{
                "task_id": "buyer-order-1", "buyer_id": "buyer",
                "provider_id": "agent", "title": "Deliver report",
                "scope": "Prepare a short report",
                "acceptance_criteria": "Include a summary",
                "due_at": None, "price_minor": 1000,
                "currency": "USD", "listing_id": "listing",
                "status": "accepted",
            }]

    queue = Queue()
    observed = []
    def worker(store):
        observed.append(list(store.items))
        return {"status": "completed"}

    stats = supervise(queue, agreements=Agreements(), poll_seconds=0.1,
                      max_cycles=1, worker=worker)
    assert stats == {"cycles": 1, "completed": 1, "idle": 0, "errors": 0}
    assert observed == [["accepted-order:buyer-order-1"]]

def test_supervisor_exports_completed_order_worker_output(tmp_path):
    queue = TaskStore(tmp_path / "economy.sqlite3")
    order = {
        "task_id": "buyer-order-export", "title": "Example deliverable",
        "scope": "Prepare a structured execution brief",
        "acceptance_criteria": "Include the agreed scope",
        "due_at": None, "price_minor": 1000, "currency": "USD",
        "buyer_id": "buyer-1", "provider_id": "agent-1",
    }

    class Agreements:
        def accepted_orders(self, *, limit):
            return [{
                **order, "listing_id": "listing-1", "status": "accepted",
                "created_at": "2026-01-01T00:00:00+00:00",
            }][:limit]

    def worker(store):
        task = store.claim(allowed_agent_ids=["order-delivery-agent"])
        assert task is not None
        draft = (
            "# Customer order execution draft\n\n"
            "**Status:** DRAFT — not delivered or buyer-approved\n\n"
            f"**Order:** {order['title']}\n"
            f"**Task ID:** {order['task_id']}\n\n"
            "## Payment status\nNot verified. No payment was collected or recorded.\n"
        )
        return store.finish(task["task_id"], draft, task["lease_token"])

    stats = supervise(queue, agreements=Agreements(), poll_seconds=0.1,
                      max_cycles=1, worker=worker)
    assert stats["completed"] == 1
    files = list((tmp_path / "deliverables").glob("*.md"))
    assert len(files) == 1
    assert order["task_id"] in files[0].read_text()


def test_supervisor_runs_optional_ai_worker_lane():
    calls = []

    def normal_worker(_store):
        calls.append("sandbox")
        return None

    def ai_worker(_store):
        calls.append("model")
        return {"status": "completed", "assigned_agent": "ai-product-copy-agent"}

    stats = supervise(Store(), poll_seconds=0.1, max_cycles=1,
                      worker=normal_worker, ai_worker=ai_worker)
    assert calls == ["sandbox", "model"]
    assert stats == {"cycles": 1, "completed": 1, "idle": 0, "errors": 0}


def test_supervisor_continues_ai_lane_after_builtin_worker_error():
    calls = []

    def normal_worker(_store):
        raise RuntimeError("sandbox unavailable")

    def ai_worker(_store):
        calls.append("model")
        return {"status": "completed", "assigned_agent": "ai-product-copy-agent"}

    stats = supervise(Store(), poll_seconds=0.1, max_cycles=1,
                      worker=normal_worker, ai_worker=ai_worker)
    assert calls == ["model"]
    assert stats == {"cycles": 1, "completed": 1, "idle": 0, "errors": 1}
