from __future__ import annotations

import json
from types import SimpleNamespace

from economy.ai_task_worker import AI_AGENT_ID, queue_product_copy_task, run_once
from economy.task_store import TaskStore


class FakeProvider:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def configured(self):
        return True

    def generate(self, prompt, *, system, max_tokens=512):
        self.calls += 1
        return SimpleNamespace(text=json.dumps(self.response))


def facts():
    return {
        "product_name": "MOBA Objective Props",
        "buyer_segment": "Indie game developers",
        "product_summary": "Five original low-poly props.",
        "included_files": ["five GLB models", "Godot 4 demo scene"],
        "formats": ["GLB", "Godot 4"],
        "known_limits": ["static props only", "no animation", "no rigging"],
        "ai_disclosure": "AI-assisted procedural mesh generation.",
    }


def valid_copy():
    return {
        "title": "MOBA Objective Props - Five Low-Poly GLB Models",
        "short_description": "Five low-poly fantasy props in GLB format for Godot 4 prototypes.",
        "description": (
            "MOBA Objective Props is a small collection of five original low-poly fantasy props. "
            "The download includes five GLB models and a Godot 4 demo scene. "
            "These are static props only, with no animation or rigging. "
            "AI-assisted procedural mesh generation."
        ),
        "tags": ["low-poly", "GLB models", "Godot assets"],
        "ai_disclosure": "AI-assisted procedural mesh generation.",
        "claims_to_verify": ["Inspect import scale and materials in Godot."],
    }


def test_queue_copy_is_idempotent_and_single_attempt(tmp_path):
    store = TaskStore(tmp_path / "economy.sqlite3")
    first = queue_product_copy_task(store, facts())
    second = queue_product_copy_task(store, facts())
    assert first["task_id"] == second["task_id"]
    assert first["assigned_agent"] == AI_AGENT_ID
    assert first["max_attempts"] == 1
    assert first["status"] == "queued"


def test_ai_worker_completes_only_its_own_queued_task(tmp_path):
    store = TaskStore(tmp_path / "economy.sqlite3")
    queued = queue_product_copy_task(store, facts())
    store.enqueue("ordinary task", "do not claim", "opportunity-researcher")
    provider = FakeProvider(valid_copy())
    result = run_once(store, provider)
    assert result["task_id"] == queued["task_id"]
    assert result["status"] == "completed"
    assert result["assigned_agent"] == AI_AGENT_ID
    payload = json.loads(result["result"])
    assert payload["published"] is False
    assert payload["status"] == "draft"
    assert provider.calls == 1
    assert store.list_tasks()[1]["status"] == "queued"


def test_ai_worker_without_credentials_leaves_tasks_queued(tmp_path):
    store = TaskStore(tmp_path / "economy.sqlite3")
    queued = queue_product_copy_task(store, facts())

    class Unconfigured:
        def configured(self):
            return False

    assert run_once(store, Unconfigured()) is None
    assert store.get(queued["task_id"])["status"] == "queued"


def test_ai_worker_fails_invalid_model_output_without_retry(tmp_path):
    store = TaskStore(tmp_path / "economy.sqlite3")
    queued = queue_product_copy_task(store, facts())
    provider = FakeProvider({"unsafe": "not a listing"})
    result = run_once(store, provider)
    assert result["task_id"] == queued["task_id"]
    assert result["status"] == "failed"
    assert "ProductCopyValidationError" in result["result"]
    assert store.get(queued["task_id"])["attempts"] == 1
